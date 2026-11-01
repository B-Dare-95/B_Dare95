# -*- coding: utf-8 -*-
"""Revit adapter against API stubs - boundary reading, links, probes,
parameters, writing."""
from __future__ import division
import revit_stubs as S
DB = S.install()

from harness import check, close, run_suite                  # noqa: E402
from dlc_roomarea import revit_io, engine, geometry as g     # noqa: E402

GAP = 200.0 / 304.8
ST = {'EXTERIOR_FUNCTIONS': engine.DEFAULT_EXTERIOR_FUNCTIONS,
      'BRIDGE_COLUMNS': True, 'DEDUCT_FREESTANDING_COLUMNS': False,
      'CURTAIN_WALL_DEPTH': 0.5, 'PROBE_GAP': GAP}


def build_scene():
    doc = S.Document('Tower_A_ARC')
    link = S.Document('Tower_A_STR')
    lvl = S.Level(doc, 'L01', 10.0)
    phase = S.Phase(doc, None, 'New Construction')
    ext = S.WallType(doc, 'EXT 250', 1)
    intw = S.WallType(doc, 'INT 150', 0)
    shaft = S.WallType(doc, 'SHAFT 200', 0)
    w_ext = S.Wall(doc, ext, 1.0)
    w_int = S.Wall(doc, intw, 0.5)
    w_shaft = S.Wall(doc, shaft, 0.6)
    col = S.Element(doc, S.Category(S.BuiltInCategory.OST_StructuralColumns,
                                    'Structural Columns'), 'C1')
    l_ext_t = S.WallType(link, 'STR RC 300', 1)
    l_wall = S.Wall(link, l_ext_t, 1.2)
    li = S.RevitLinkInstance(doc, link, 'STR link')
    seg = S.BoundarySegment
    I = lambda e: e.Id
    room_a = S.Room(doc, '101', 'Office', lvl, (0, 0, 10, 8), phase,
                    area=79.7, loops=[[
                        seg([(0, 0), (4, 0)], I(w_ext)),
                        seg([(4, 0), (4, 0.3)], I(col)),
                        seg([(4, 0.3), (5, 0.3)], I(col)),
                        seg([(5, 0.3), (5, 0)], I(col)),
                        seg([(5, 0), (10, 0)], I(w_ext)),
                        seg([(10, 0), (10, 8)], I(w_int)),
                        seg([(10, 8), (0, 8)], I(w_ext)),
                        seg([(0, 8), (0, 0)], I(w_ext))]])
    # room B given clockwise, right wall comes from the structural link
    room_b = S.Room(doc, '102', 'Retail', lvl, (10.5, 0, 20, 8), phase,
                    area=76.0, loops=[[
                        seg([(10.5, 0), (10.5, 8)], I(w_int)),
                        seg([(10.5, 8), (20, 8)], I(w_shaft)),
                        seg([(20, 8), (20, 0)], I(li), I(l_wall)),
                        seg([(20, 0), (10.5, 0)], I(w_ext))]])
    room_b.params['DLC_Is_Leasable'] = S.Parameter(1, 'int')
    room_a.params['DLC_Is_Leasable'] = S.Parameter(None, 'int')
    return locals()


# --------------------------------------------------------------------------
def test_id_value_uses_value_not_integervalue():
    check(revit_io.id_value(S.ElementId(42)) == 42)


def test_describe_host_and_linked_walls():
    sc = build_scene()
    doc = sc['doc']
    d = revit_io.describe_bounding(doc, S.BoundarySegment(
        [(0, 0), (1, 0)], sc['w_ext'].Id))
    check(d['kind'] == g.KIND_WALL and d['function'] == 'EXTERIOR')
    check(d['width'] == 1.0 and d['label'].startswith('EXT 250'))
    check(d['extra_flags'] == [])
    d = revit_io.describe_bounding(doc, S.BoundarySegment(
        [(0, 0), (1, 0)], sc['li'].Id, sc['l_wall'].Id))
    check(d['kind'] == g.KIND_WALL and d['width'] == 1.2)
    check(d['label'].startswith('[Tower_A_STR] STR RC 300'))
    check('LINKED_WALL' in d['extra_flags'])


def test_describe_other_elements():
    sc = build_scene()
    doc = sc['doc']
    sep = S.Element(doc, S.Category(S.BuiltInCategory.OST_RoomSeparationLines,
                                    'Room Separation'))
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          sep.Id))
    check(d['kind'] == g.KIND_SEPARATION)
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          sc['col'].Id))
    check(d['kind'] == g.KIND_COLUMN)
    arch_col = S.Element(doc, S.Category(S.BuiltInCategory.OST_Columns, 'C'))
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          arch_col.Id))
    check(d['kind'] == g.KIND_COLUMN)
    gm = S.Element(doc, S.Category(S.BuiltInCategory.OST_GenericModel,
                                   'Generic Models'))
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          gm.Id))
    check(d['kind'] == g.KIND_OTHER and 'Generic Models' in d['label'])
    d = revit_io.describe_bounding(doc, S.BoundarySegment(
        [(0, 0), (1, 0)], S.ElementId.InvalidElementId))
    check(d['kind'] == g.KIND_OTHER)


def test_describe_unloaded_link_and_odd_walls():
    sc = build_scene()
    doc = sc['doc']
    dead = S.RevitLinkInstance(doc, None, 'Unloaded STR')
    d = revit_io.describe_bounding(doc, S.BoundarySegment(
        [(0, 0), (1, 0)], dead.Id, S.ElementId(5)))
    check(d['kind'] == g.KIND_OTHER and 'Unloaded' in d['label'])
    member = S.Wall(doc, sc['ext'], 0.9)
    stacked = S.Wall(doc, S.WallType(doc, 'STACK', 1, S.WallKind.Stacked),
                     None, [member])
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          stacked.Id))
    check(d['width'] == 0.9 and 'STACKED_WALL' in d['extra_flags'])
    nofunc = S.Wall(doc, S.WallType(doc, 'NOFUNC', None), 0.4)
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          nofunc.Id))
    check(d['function'] is None)
    cw = S.Wall(doc, S.WallType(doc, 'CW', 1, S.WallKind.Curtain), 0.0)
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          cw.Id))
    check(d['is_curtain'] and d['width'] == 0.0)
    broken = S.Wall(doc, sc['ext'], None)
    d = revit_io.describe_bounding(doc, S.BoundarySegment([(0, 0), (1, 0)],
                                                          broken.Id))
    check(d['width'] is None)


def test_extract_uses_finish_and_probes_behind():
    sc = build_scene()
    doc, a = sc['doc'], sc['room_a']
    loops = revit_io.extract_loops(doc, a, ST)
    check(a.boundary_calls == ['Finish'], 'must read finish-face boundary')
    walls = [s for s in loops[0] if s['kind'] == g.KIND_WALL]
    behind = dict((s['label'].split(' [')[0] + str(s['pts'][0]),
                   s['room_behind']) for s in walls)
    check(sum(1 for s in walls if s['room_behind']) == 1,
          'only the party wall has a room behind')
    check(all(abs(z - 11.0) < 1e-9 for _, _, z in doc.probes),
          'probe 1 ft above level')
    check(len(doc.probes) == len(walls))
    check(behind is not None)


def test_end_to_end_room_a():
    sc = build_scene()
    loops = revit_io.extract_loops(sc['doc'], sc['room_a'], ST)
    r = engine.compute_room(loops, ST)
    close(r['gla'], 10.25 * 8)
    close(r['gfa'], 11.25 * 10)
    close(r['base'], 80 - 0.3)
    check(r['flags'] == [])


def test_end_to_end_room_b_link_and_shaft():
    sc = build_scene()
    loops = revit_io.extract_loops(sc['doc'], sc['room_b'], ST)
    r = engine.compute_room(loops, ST)
    close(r['gla'], 9.75 * 8.3)
    close(r['gfa'], 10.95 * 9.3)
    flags = [f for w in r['walls'] for f in w['flags']]
    check('LINKED_WALL' in flags)
    check('INT_TYPE_NOTHING_BEHIND' in flags, 'shaft wall flagged')
    check(revit_io.read_yes_no(sc['room_b'], 'DLC_Is_Leasable') is True)
    check(revit_io.read_yes_no(sc['room_a'], 'DLC_Is_Leasable') is None)
    check(revit_io.read_yes_no(sc['room_a'], 'Missing') is None)


def test_no_phase_means_no_probe():
    sc = build_scene()
    sc['room_a'].params['ROOM_PHASE'] = S.Parameter(None, 'id')
    loops = revit_io.extract_loops(sc['doc'], sc['room_a'], ST)
    check(all(s.get('room_behind') is None for s in loops[0]
              if s['kind'] == g.KIND_WALL))
    r = engine.compute_room(loops, ST)
    close(r['gla'], 10.25 * 8)      # Function still decides


def test_collect_rooms_scopes():
    sc = build_scene()
    doc, lvl = sc['doc'], sc['lvl']
    S.Room(doc, '199', 'Unplaced', lvl, None, None, 0.0, placed=False)
    lvl2 = S.Level(doc, 'L02', 20.0)
    S.Room(doc, '201', 'Up', lvl2, None, None, 50.0)
    doc.ActiveView = S.View(lvl)
    rooms, msg = revit_io.collect_rooms(doc, S.UIDocument([]), 'ALL')
    check(len(rooms) == 3 and '1 unplaced' in msg)
    rooms, msg = revit_io.collect_rooms(doc, S.UIDocument([]), 'LEVEL')
    check(sorted(revit_io.room_number(r) for r in rooms) == ['101', '102'])
    doc.ActiveView = S.View(None)
    rooms, msg = revit_io.collect_rooms(doc, S.UIDocument([]), 'LEVEL')
    check(rooms == [] and 'no level' in msg)
    rooms, msg = revit_io.collect_rooms(
        doc, S.UIDocument([sc['w_ext'].Id, sc['room_b'].Id]), 'SELECTION')
    check(len(rooms) == 1 and revit_io.room_number(rooms[0]) == '102')
    rooms, msg = revit_io.collect_rooms(doc, S.UIDocument([sc['w_ext'].Id]),
                                        'SELECTION')
    check(rooms == [] and 'No rooms are selected' in msg)


SPECS = [('DLC_GLA', 'g-gla', 'AREA', 'x'), ('DLC_GFA', 'g-gfa', 'AREA', 'x'),
         ('DLC_Is_Leasable', 'g-l', 'YESNO', 'x')]


def test_check_parameters():
    doc = S.Document()
    missing, problems = revit_io.check_parameters(doc, SPECS)
    check(missing == ['DLC_GLA', 'DLC_GFA', 'DLC_Is_Leasable'] and not problems)
    rooms_cs = S.CategorySet()
    rooms_cs.Insert(S.Category(S.BuiltInCategory.OST_Rooms, 'Rooms'))
    doc.ParameterBindings.items.append(
        (S.Definition('DLC_GLA', 'autodesk.spec:spec.string'),
         S.InstanceBinding(rooms_cs)))
    doors = S.CategorySet()
    doors.Insert(S.Category(S.BuiltInCategory.OST_Walls, 'Walls'))
    doc.ParameterBindings.items.append(
        (S.Definition('DLC_GFA', S.SpecTypeId.Area), S.InstanceBinding(doors)))
    doc.ParameterBindings.items.append(
        (S.Definition('DLC_Is_Leasable', S.SpecTypeId.Boolean.YesNo),
         object()))                                 # a TypeBinding
    missing, problems = revit_io.check_parameters(doc, SPECS)
    check(missing == ['DLC_GFA'], 'GFA bound to other category -> missing')
    check(len(problems) == 2)
    check('is not an Area parameter' in problems[0], problems[0])
    check('TYPE parameter' in problems[1])


def test_ensure_parameters_creates_with_fixed_guids():
    doc, app = S.Document(), S.Application()
    created = revit_io.ensure_parameters(doc, app, SPECS)
    check(created == ['DLC_GLA', 'DLC_GFA', 'DLC_Is_Leasable'])
    check(app.SharedParametersFilename == r'C:\Firm\Firm_SharedParams.txt',
          'user shared parameter file restored')
    check(app.opened and 'DLC_RoomAreas' in app.opened[0])
    defs = dict((d.Name, d) for d, b in doc.ParameterBindings.items)
    check(defs['DLC_GLA'].guid == ('GUID', 'g-gla'))
    check(defs['DLC_Is_Leasable'].spec == S.SpecTypeId.Boolean.YesNo)
    rooms = S.Category(S.BuiltInCategory.OST_Rooms, 'Rooms')
    check(all(b.Categories.Contains(rooms)
              for d, b in doc.ParameterBindings.items))
    # second run: nothing to do
    check(revit_io.ensure_parameters(doc, app, SPECS) == [])


def test_ensure_parameters_restores_file_on_failure():
    doc, app = S.Document(), S.Application()
    app.fail_open = True
    try:
        revit_io.ensure_parameters(doc, app, SPECS)
        check(False, 'should raise')
    except Exception as ex:
        check('cannot open' in str(ex))
    check(app.SharedParametersFilename == r'C:\Firm\Firm_SharedParams.txt')
    doc2, app2 = S.Document(), S.Application()
    doc2.ParameterBindings.refuse = True
    try:
        revit_io.ensure_parameters(doc2, app2, SPECS)
        check(False, 'should raise')
    except RuntimeError as ex:
        check('refused' in str(ex))
    check(app2.SharedParametersFilename == r'C:\Firm\Firm_SharedParams.txt')


def test_ensure_parameters_adds_rooms_to_existing_binding():
    doc, app = S.Document(), S.Application()
    walls = S.CategorySet()
    walls.Insert(S.Category(S.BuiltInCategory.OST_Walls, 'Walls'))
    doc.ParameterBindings.items.append(
        (S.Definition('DLC_GFA', S.SpecTypeId.Area), S.InstanceBinding(walls)))
    created = revit_io.ensure_parameters(doc, app, SPECS)
    check('DLC_GFA (added to Rooms)' in created)
    rooms = S.Category(S.BuiltInCategory.OST_Rooms, 'Rooms')
    b = dict((d.Name, b) for d, b in doc.ParameterBindings.items)['DLC_GFA']
    check(b.Categories.Contains(rooms) and len(b.Categories.items) == 2)


def test_write_area_failure_modes():
    el = S.Element(S.Document())
    for params, text in (({}, 'missing'),
                         ({'P': S.Parameter(0.0, read_only=True)}, 'read-only'),
                         ({'P': S.Parameter(0.0, reject=True)}, 'rejected')):
        el.params = params
        try:
            revit_io.write_area(el, 'P', 12.5)
            check(False, 'should raise')
        except RuntimeError as ex:
            check(text in str(ex), str(ex))
    el.params = {'P': S.Parameter(0.0)}
    revit_io.write_area(el, 'P', 12.5)
    check(el.params['P'].value == 12.5)


def test_owned_by_other():
    doc = S.Document(workshared=False)
    el = S.Element(doc)
    check(revit_io.owned_by_other(doc, el) is None)
    doc.IsWorkshared = True
    check(revit_io.owned_by_other(doc, el) is None)
    S.WorksharingUtils.owners[el.Id.Value] = 'sara.k'
    check(revit_io.owned_by_other(doc, el) == 'sara.k')
    del S.WorksharingUtils.owners[el.Id.Value]


def test_temp_spf_written_fresh_with_crlf():
    import os
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), 'DLC_RoomAreas_SharedParams.txt')
    with open(tmp, 'wb') as f:
        f.write(b'stale content from an old run')
    revit_io.ensure_parameters(S.Document(), S.Application(), SPECS)
    data = open(tmp, 'rb').read()
    check(data.startswith(b'# This is a Revit shared parameter file.\r\n'))
    check(b'\r\r\n' not in data and b'stale' not in data)


TESTS = [test_id_value_uses_value_not_integervalue,
         test_temp_spf_written_fresh_with_crlf,
         test_describe_host_and_linked_walls, test_describe_other_elements,
         test_describe_unloaded_link_and_odd_walls,
         test_extract_uses_finish_and_probes_behind, test_end_to_end_room_a,
         test_end_to_end_room_b_link_and_shaft, test_no_phase_means_no_probe,
         test_collect_rooms_scopes, test_check_parameters,
         test_ensure_parameters_creates_with_fixed_guids,
         test_ensure_parameters_restores_file_on_failure,
         test_ensure_parameters_adds_rooms_to_existing_binding,
         test_write_area_failure_modes, test_owned_by_other]


def run():
    return run_suite('revit_io (stubs)', TESTS)

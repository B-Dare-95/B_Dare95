# -*- coding: utf-8 -*-
"""Runs the real pushbutton bd_family_cleaner.py against stubs (no WPF window shown)."""
from __future__ import division
import imp_helper
import os
import shutil
import sys
import tempfile
import types
import revit_stubs as S
from harness import check, close, run_suite, ROOT

SCRIPT = os.path.join(ROOT, 'DLC.extension', 'DLC.tab', 'Rooms.panel',
                      'Room Areas.pushbutton', 'bd_family_cleaner.py')


def load_script(doc, uidoc, save_path):
    S.install()
    clr = types.ModuleType('clr')
    clr.AddReference = lambda n: None
    clr.GetClrType = lambda t: t
    sys.modules['clr'] = clr
    for name in ('System.Data', 'System.Windows', 'System.Windows.Input'):
        sys.modules[name] = types.ModuleType(name)
    sys.modules['System.Data'].DataTable = object
    sys.modules['System.Windows.Input'].Mouse = object()
    sys.modules['System.Windows.Input'].Cursors = object()
    pyrevit = types.ModuleType('pyrevit')
    pyrevit.revit = types.SimpleNamespace(doc=doc, uidoc=uidoc)
    alerts = []
    pyrevit.forms = types.SimpleNamespace(
        WPFWindow=object, alert=lambda *a, **k: alerts.append(a),
        save_file=lambda **k: save_path)
    pyrevit.script = types.SimpleNamespace(get_config=None, save_config=None)
    sys.modules['pyrevit'] = pyrevit
    mod = imp_helper.load_source('dlc_room_areas_script', SCRIPT)
    return mod, alerts


def scene():
    import test_revit_io as T
    sc = T.build_scene()
    doc = sc['doc']
    doc.Application = S.Application()
    doc.IsFamilyDocument = False
    doc.Regenerate = lambda: None
    return sc, doc


def test_measure_write_export():
    sc, doc = scene()
    d = tempfile.mkdtemp()
    try:
        out = os.path.join(d, 'report.xlsx')
        mod, alerts = load_script(doc, S.UIDocument([]), out)
        rooms = [sc['room_a'], sc['room_b']]
        res = mod.measure_rooms(rooms, False)
        a = [r for r in res if r['number'] == '101'][0]
        b = [r for r in res if r['number'] == '102'][0]
        check(a['leasable'] is False and a['leasable_blank'])
        check(a['gla'] == 0.0)
        close(a['gla_measured'], 10.25 * 8)
        close(b['gla'], 9.75 * 8.3)
        res2 = mod.measure_rooms(rooms, True)
        close([r for r in res2 if r['number'] == '101'][0]['gla'], 10.25 * 8)

        S.Transaction.log[:] = []
        S.WorksharingUtils.owners[sc['room_b'].Id.Value] = 'sara.k'
        doc.IsWorkshared = True
        summ = mod.write_results(res)
        del S.WorksharingUtils.owners[sc['room_b'].Id.Value]
        check(summ['written'] == 1 and summ['owned'] == 1, str(summ))
        check(len(summ['created']) == 3)
        close(sc['room_a'].LookupParameter('DLC_GFA').value, 11.25 * 10)
        check(sc['room_a'].LookupParameter('DLC_GLA').value == 0.0)
        check(S.Transaction.log[0][0] == 'start' and
              S.Transaction.log[-1][0] == 'commit')
        check('borrowed by sara.k' in b['write_error'])
        p = mod.export_results(res)
        check(p == out and os.path.exists(out))
    finally:
        shutil.rmtree(d)


def test_write_stops_on_wrong_param_type():
    sc, doc = scene()
    rooms_cs = S.CategorySet()
    rooms_cs.Insert(S.Category(S.BuiltInCategory.OST_Rooms, 'Rooms'))
    doc.ParameterBindings.items.append(
        (S.Definition('DLC_GLA', 'autodesk.spec:spec.string'),
         S.InstanceBinding(rooms_cs)))
    mod, _ = load_script(doc, S.UIDocument([]), None)
    res = mod.measure_rooms([sc['room_a']], False)
    S.Transaction.log[:] = []
    summ = mod.write_results(res)
    check('fatal' in summ and 'not an Area' in summ['fatal'])
    check(S.Transaction.log == [], 'no transaction opened')


def test_write_rolls_back_on_unexpected_error():
    sc, doc = scene()
    mod, _ = load_script(doc, S.UIDocument([]), None)
    res = mod.measure_rooms([sc['room_a']], False)
    doc.Application.fail_open = True
    S.Transaction.log[:] = []
    summ = mod.write_results(res)
    check('rolled back' in summ.get('fatal', ''))
    check(S.Transaction.log[-1][0] == 'rollback')


def test_unmeasurable_room_reported():
    sc, doc = scene()
    lvl = sc['lvl']
    bad = S.Room(doc, '900', 'Open', lvl, None, sc['phase'], 10.0, loops=[])
    mod, _ = load_script(doc, S.UIDocument([]), None)
    res = mod.measure_rooms([bad], False)
    check('error' in res[0])


def test_xaml_names_match_script():
    import re
    import xml.etree.ElementTree as ET
    src = open(SCRIPT).read()
    xaml = re.search(r"XAML = u'''(.*?)'''", src, re.S).group(1)
    root = ET.fromstring(xaml)
    names = set(el.get('{http://schemas.microsoft.com/winfx/2006/xaml}Name')
                for el in root.iter()) - set([None])
    used = set(re.findall(r'self\.((?:scope|chk|btn|txt|grid)\w*)\b(?!\()', src))
    check(used <= names, 'missing in XAML: %s' % (used - names))
    check(names <= used, 'unused XAML names: %s' % (names - used))


TESTS = [test_measure_write_export, test_write_stops_on_wrong_param_type,
         test_write_rolls_back_on_unexpected_error,
         test_unmeasurable_room_reported, test_xaml_names_match_script]


def run():
    return run_suite('bd_family_cleaner.py (integration)', TESTS)

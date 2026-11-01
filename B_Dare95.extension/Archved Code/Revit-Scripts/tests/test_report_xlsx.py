# -*- coding: utf-8 -*-
"""Report builder + xlsx writer (validated by reading back with openpyxl)."""
from __future__ import division
import os
import shutil
import tempfile
import zipfile
from harness import check, close, run_suite
from dlc_roomarea import report, xlsx

F = 1 / 0.09290304           # ft2 per m2


def sample():
    return [
        {'number': '102', 'name': 'Retail', 'level': 'L01', 'level_elev': 10,
         'leasable': True, 'gla': 80 * F, 'gfa': 100 * F, 'base': 78 * F,
         'revit_area': 78 * F, 'flags': [], 'walls': [
             {'label': 'SHAFT [1]', 'flags': ['INT_TYPE_NOTHING_BEHIND']},
             {'label': 'SHAFT [1]', 'flags': ['INT_TYPE_NOTHING_BEHIND']},
             {'label': '[STR] RC [9]', 'flags': ['LINKED_WALL']}]},
        {'number': '101', 'name': u'Café & <Lobby>', 'level': 'L01',
         'level_elev': 10, 'leasable': False, 'gla': 0.0, 'gfa': 50 * F,
         'base': 45 * F, 'revit_area': 45 * F, 'flags': ['LEASABLE_BLANK'],
         'walls': []},
        {'number': 'B01', 'name': 'Store', 'level': 'B1', 'level_elev': -12,
         'leasable': True, 'gla': 20 * F, 'gfa': 25 * F, 'base': 19 * F,
         'revit_area': 19 * F, 'flags': [], 'walls': [],
         'write_error': 'Room is borrowed by sara.k'},
        {'number': '103', 'name': 'Broken', 'level': 'L01', 'level_elev': 10,
         'revit_area': 5 * F, 'error': 'Could not measure'},
    ]


def test_totals_and_qa():
    t = report.totals(sample())
    check(t['rooms'] == 3 and t['leasable'] == 2)
    close(report.m2(t['gla']), 100.0)
    close(report.m2(t['gfa']), 175.0)
    qa = report.qa_items(sample()[0])
    check(len(qa) == 1, 'duplicate wall flags collapsed, LINKED_WALL hidden')
    check(report.qa_items(sample()[2])[0][0] == 'Not written')
    check(report.qa_items(sample()[3])[0][0] == 'Not measured')


def test_sheets_layout():
    sh = report.build_sheets(sample())
    check([s['name'] for s in sh] == ['ROOMS', 'LEVELS', 'QA'])
    rooms = sh[0]['rows']
    check(rooms[0][0] == 'B1', 'sorted by level elevation')
    check(rooms[-1]['values'][4] == 100.0 and rooms[-1]['values'][5] == 175.0)
    levels = sh[1]['rows']
    check(levels[0][0] == 'B1' and levels[1][0] == 'L01')
    check(levels[1][3] == 80.0 and levels[1][4] == 150.0)
    check(levels[-1]['values'][1] == 3)
    check(len(sh[2]['rows']) == 4)


def test_xlsx_roundtrip():
    import openpyxl
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, 'out.xlsx')
        xlsx.write_workbook(p, report.build_sheets(sample()))
        wb = openpyxl.load_workbook(p)
        check(wb.sheetnames == ['ROOMS', 'LEVELS', 'QA'])
        ws = wb['ROOMS']
        check(ws['A1'].value == 'Level' and ws['A1'].font.b)
        check(ws.freeze_panes == 'A2')
        names = [ws.cell(r, 3).value for r in range(2, 7)]
        check(u'Café & <Lobby>' in names, 'xml escaping round-trips')
        last = ws.max_row
        check(ws.cell(last, 1).value == 'TOTAL' and ws.cell(last, 5).font.b)
        close(ws.cell(last, 5).value, 100.0)
        check(ws.cell(2, 5).number_format == '#,##0.00')
        check(wb['QA'].max_row == 5)
    finally:
        shutil.rmtree(d)


def test_xlsx_bad_chars_and_long_names():
    import openpyxl
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, 'x.xlsx')
        xlsx.write_workbook(p, [
            {'name': 'A/B:C*very long sheet name exceeding thirty one',
             'header': ['t'], 'rows': [[u'bad\x01\x0bchar'], [True],
                                       [float('nan')], [None]]},
            {'name': 'A/B:C*very long sheet name exceeding thirty one',
             'rows': [[1]]}])
        wb = openpyxl.load_workbook(p)
        check(len(wb.sheetnames) == 2 and
              wb.sheetnames[0] != wb.sheetnames[1])
        check(all(len(n) <= 31 for n in wb.sheetnames))
        ws = wb.worksheets[0]
        check(ws['A2'].value == 'badchar' and ws['A3'].value == 'Yes')
        check(ws['A4'].value is None)
    finally:
        shutil.rmtree(d)


def test_failed_write_keeps_old_report():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, 'r.xlsx')
        xlsx.write_workbook(p, [{'name': 'S', 'rows': [['old']]}])
        before = open(p, 'rb').read()
        orig = zipfile.ZipFile.writestr

        def boom(self, name, data, *a, **k):
            if 'sheet1' in name:
                raise IOError('disk full')
            return orig(self, name, data, *a, **k)
        zipfile.ZipFile.writestr = boom
        try:
            xlsx.write_workbook(p, [{'name': 'S', 'rows': [['new']]}])
            check(False, 'should raise')
        except IOError:
            pass
        finally:
            zipfile.ZipFile.writestr = orig
        check(open(p, 'rb').read() == before, 'old report untouched')
        xlsx.write_workbook(p, [{'name': 'S', 'rows': [['new']]}])
        check(not os.path.exists(p + '.bak'))
        check(open(p, 'rb').read() != before, 'overwrite works')
    finally:
        shutil.rmtree(d)


TESTS = [test_totals_and_qa, test_sheets_layout, test_xlsx_roundtrip,
         test_xlsx_bad_chars_and_long_names, test_failed_write_keeps_old_report]


def run():
    return run_suite('report + xlsx', TESTS)

# -*- coding: utf-8 -*-
"""DLC Room Areas - turns per-room results into report sheets (pure)."""
from __future__ import division

from . import engine

SQFT_TO_SQM = 0.09290304

# flags that are information only - not listed in the QA sheet
INFO_ONLY = ('LINKED_WALL',)


def m2(ft2, decimals=2):
    return round(ft2 * SQFT_TO_SQM, decimals)


def sort_results(results):
    return sorted(results, key=lambda r: (r.get('level_elev', 0.0),
                                          r.get('level', ''),
                                          r.get('number', '')))


def qa_items(r):
    """[(item, detail)] for one room result."""
    items = []
    if r.get('error'):
        items.append(('Not measured', r['error']))
    if r.get('write_error'):
        items.append(('Not written', r['write_error']))
    for f in r.get('flags', []):
        items.append((f, engine.FLAG_TEXT.get(f, f)))
    seen = set()
    for w in r.get('walls', []):
        for f in w.get('flags', []):
            if f in INFO_ONLY:
                continue
            key = (w.get('label'), f)
            if key in seen:
                continue
            seen.add(key)
            items.append((f, '%s - %s' % (w.get('label', ''),
                                          engine.FLAG_TEXT.get(f, f))))
    return items


def totals(results):
    ok = [r for r in results if not r.get('error')]
    return {'rooms': len(ok),
            'leasable': len([r for r in ok if r.get('leasable')]),
            'gla': sum(r.get('gla', 0.0) for r in ok),
            'gfa': sum(r.get('gfa', 0.0) for r in ok),
            'qa': sum(len(qa_items(r)) for r in results)}


def build_sheets(results, decimals=2):
    results = sort_results(results)
    rooms_rows = []
    for r in results:
        notes = '; '.join(i for i, _ in qa_items(r))
        if r.get('error'):
            rooms_rows.append([r.get('level', ''), r.get('number', ''),
                               r.get('name', ''), None, None, None,
                               m2(r.get('revit_area', 0.0), decimals), None,
                               notes])
            continue
        rooms_rows.append([r.get('level', ''), r.get('number', ''),
                           r.get('name', ''),
                           'Yes' if r.get('leasable') else 'No',
                           m2(r['gla'], decimals), m2(r['gfa'], decimals),
                           m2(r.get('revit_area', 0.0), decimals),
                           m2(r.get('base', 0.0), decimals), notes])
    t = totals(results)
    rooms_rows.append({'values': ['TOTAL', '', '%d rooms' % t['rooms'],
                                  '%d leasable' % t['leasable'],
                                  m2(t['gla'], decimals),
                                  m2(t['gfa'], decimals), None, None, '']})

    levels = []
    by_level = {}
    for r in results:
        if r.get('error'):
            continue
        lv = r.get('level', '')
        if lv not in by_level:
            by_level[lv] = [0, 0, 0.0, 0.0]
            levels.append(lv)
        acc = by_level[lv]
        acc[0] += 1
        acc[1] += 1 if r.get('leasable') else 0
        acc[2] += r['gla']
        acc[3] += r['gfa']
    level_rows = [[lv, by_level[lv][0], by_level[lv][1],
                   m2(by_level[lv][2], decimals), m2(by_level[lv][3], decimals)]
                  for lv in levels]
    level_rows.append({'values': ['TOTAL', t['rooms'], t['leasable'],
                                  m2(t['gla'], decimals),
                                  m2(t['gfa'], decimals)]})

    qa_rows = []
    for r in results:
        for item, detail in qa_items(r):
            qa_rows.append([r.get('level', ''), r.get('number', ''),
                            r.get('name', ''), item, detail])
    if not qa_rows:
        qa_rows.append(['', '', '', 'OK', 'No issues found.'])

    return [
        {'name': 'ROOMS',
         'header': ['Level', 'Number', 'Name', 'Leasable', 'GLA (m2)',
                    'GFA (m2)', 'Revit Area (m2)', 'Finish-face Area (m2)',
                    'QA notes'],
         'rows': rooms_rows, 'number_cols': [4, 5, 6, 7],
         'widths': [14, 10, 28, 10, 12, 12, 15, 19, 40]},
        {'name': 'LEVELS',
         'header': ['Level', 'Rooms', 'Leasable rooms', 'GLA (m2)',
                    'GFA (m2)'],
         'rows': level_rows, 'number_cols': [3, 4],
         'widths': [16, 8, 15, 14, 14]},
        {'name': 'QA',
         'header': ['Level', 'Number', 'Name', 'Item', 'Detail'],
         'rows': qa_rows, 'widths': [14, 10, 28, 26, 90]},
    ]

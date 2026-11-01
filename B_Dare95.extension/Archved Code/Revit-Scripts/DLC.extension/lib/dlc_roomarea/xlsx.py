# -*- coding: utf-8 -*-
"""Minimal dependency-free .xlsx writer (zipfile only). IronPython 2.7 safe.

write_workbook(path, sheets)
  sheets: list of dicts {name, header, rows, widths(optional), number_cols}
  number_cols: set of column indexes shown with 2 decimals.
The file is written to a temp name first and swapped in only when complete,
so a failed export never destroys an existing report.
"""
from __future__ import division
import os
import re
import zipfile

_BAD = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1f]')

try:
    _text = unicode          # noqa: F821  (IronPython / Py2)
except NameError:
    _text = str


def _esc(v):
    s = _text(v)
    s = _BAD.sub(u'', s)
    return (s.replace(u'&', u'&amp;').replace(u'<', u'&lt;')
             .replace(u'>', u'&gt;').replace(u'"', u'&quot;'))


def _col(n):
    s = ''
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_name(name, used):
    name = re.sub(r'[\[\]\*\?/\\:]', '_', name)[:31] or 'Sheet'
    base, k = name, 2
    while name.lower() in used:
        suffix = '_%d' % k
        name = base[:31 - len(suffix)] + suffix
        k += 1
    used.add(name.lower())
    return name


def _cell(ref, v, style_num, style_text):
    if v is None or v == '':
        return u''
    if isinstance(v, bool):
        return u'<c r="%s" t="inlineStr"%s><is><t>%s</t></is></c>' % (
            ref, style_text, u'Yes' if v else u'No')
    if isinstance(v, (int, float)):
        if v != v or v in (float('inf'), float('-inf')):
            return u''
        return u'<c r="%s"%s><v>%r</v></c>' % (ref, style_num, float(v))
    return u'<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t>' \
           u'</is></c>' % (ref, style_text, _esc(v))


def _sheet_xml(sheet):
    header = sheet.get('header') or []
    rows = sheet.get('rows') or []
    numcols = set(sheet.get('number_cols') or [])
    widths = sheet.get('widths') or []
    out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           u'<worksheet xmlns="http://schemas.openxmlformats.org/'
           u'spreadsheetml/2006/main">']
    if header:
        out.append(u'<sheetViews><sheetView workbookViewId="0">'
                   u'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft"'
                   u' state="frozen"/></sheetView></sheetViews>')
    if widths:
        out.append(u'<cols>')
        for i, w in enumerate(widths):
            out.append(u'<col min="%d" max="%d" width="%s" customWidth="1"/>'
                       % (i + 1, i + 1, w))
        out.append(u'</cols>')
    out.append(u'<sheetData>')
    r = 1
    if header:
        cells = [_cell('%s1' % _col(i), h, u' s="1"', u' s="1"')
                 for i, h in enumerate(header)]
        out.append(u'<row r="1">%s</row>' % u''.join(cells))
        r = 2
    for row in rows:
        bold = isinstance(row, dict)
        vals = row['values'] if bold else row
        cells = []
        for i, v in enumerate(vals):
            if bold:
                sn, st = u' s="3"', u' s="1"'
            else:
                sn = u' s="2"' if i in numcols else u''
                st = u''
            cells.append(_cell('%s%d' % (_col(i), r), v, sn, st))
        out.append(u'<row r="%d">%s</row>' % (r, u''.join(cells)))
        r += 1
    out.append(u'</sheetData></worksheet>')
    return u''.join(out)


_STYLES = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<styleSheet xmlns="http://schemas.openxmlformats.org/'
           u'spreadsheetml/2006/main">'
           u'<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/>'
           u'</numFmts>'
           u'<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
           u'<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
           u'<fills count="2"><fill><patternFill patternType="none"/></fill>'
           u'<fill><patternFill patternType="gray125"/></fill></fills>'
           u'<borders count="1"><border><left/><right/><top/><bottom/>'
           u'<diagonal/></border></borders>'
           u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
           u'borderId="0"/></cellStyleXfs>'
           u'<cellXfs count="4">'
           u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           u'<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" '
           u'applyFont="1"/>'
           u'<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" '
           u'applyNumberFormat="1"/>'
           u'<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" '
           u'applyNumberFormat="1" applyFont="1"/>'
           u'</cellXfs>'
           u'<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
           u'builtinId="0"/></cellStyles></styleSheet>')


def write_workbook(path, sheets):
    used = set()
    names = [_sheet_name(s.get('name', 'Sheet'), used) for s in sheets]
    ct = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          u'content-types">',
          u'<Default Extension="rels" ContentType="application/'
          u'vnd.openxmlformats-package.relationships+xml"/>',
          u'<Default Extension="xml" ContentType="application/xml"/>',
          u'<Override PartName="/xl/workbook.xml" ContentType="application/'
          u'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
          u'<Override PartName="/xl/styles.xml" ContentType="application/'
          u'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    wb = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
          u'2006/main" xmlns:r="http://schemas.openxmlformats.org/'
          u'officeDocument/2006/relationships"><sheets>']
    rels = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            u'<Relationships xmlns="http://schemas.openxmlformats.org/'
            u'package/2006/relationships">']
    for i, n in enumerate(names):
        k = i + 1
        ct.append(u'<Override PartName="/xl/worksheets/sheet%d.xml" '
                  u'ContentType="application/vnd.openxmlformats-'
                  u'officedocument.spreadsheetml.worksheet+xml"/>' % k)
        wb.append(u'<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
                  % (_esc(n), k, k))
        rels.append(u'<Relationship Id="rId%d" Type="http://schemas.'
                    u'openxmlformats.org/officeDocument/2006/relationships/'
                    u'worksheet" Target="worksheets/sheet%d.xml"/>' % (k, k))
    n = len(names)
    rels.append(u'<Relationship Id="rId%d" Type="http://schemas.'
                u'openxmlformats.org/officeDocument/2006/relationships/styles"'
                u' Target="styles.xml"/>' % (n + 1))
    ct.append(u'</Types>')
    wb.append(u'</sheets></workbook>')
    rels.append(u'</Relationships>')
    root_rels = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 u'<Relationships xmlns="http://schemas.openxmlformats.org/'
                 u'package/2006/relationships"><Relationship Id="rId1" '
                 u'Type="http://schemas.openxmlformats.org/officeDocument/'
                 u'2006/relationships/officeDocument" Target="xl/workbook.xml"'
                 u'/></Relationships>')

    tmp = path + '.tmp'
    z = zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED)
    try:
        z.writestr('[Content_Types].xml', u''.join(ct).encode('utf-8'))
        z.writestr('_rels/.rels', root_rels.encode('utf-8'))
        z.writestr('xl/workbook.xml', u''.join(wb).encode('utf-8'))
        z.writestr('xl/_rels/workbook.xml.rels', u''.join(rels).encode('utf-8'))
        z.writestr('xl/styles.xml', _STYLES.encode('utf-8'))
        for i, s in enumerate(sheets):
            z.writestr('xl/worksheets/sheet%d.xml' % (i + 1),
                       _sheet_xml(s).encode('utf-8'))
    finally:
        z.close()

    # swap in: keep the old file until the new one is fully in place
    bak = None
    if os.path.exists(path):
        bak = path + '.bak'
        if os.path.exists(bak):
            os.remove(bak)
        os.rename(path, bak)
    try:
        os.rename(tmp, path)
    except Exception:
        if bak:
            os.rename(bak, path)
        raise
    if bak and os.path.exists(bak):
        os.remove(bak)
    return path

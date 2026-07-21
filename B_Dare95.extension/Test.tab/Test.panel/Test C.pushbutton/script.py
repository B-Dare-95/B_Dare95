# -*- coding: utf-8 -*-
"""Unused family type report per Model & Annotation category.

For every Model and Annotation category, groups element types by their
family and reports how many instances each type has in the project.
Types with zero instances are flagged as NOT USED.
Read-only: no transaction required.
"""

from pyrevit import revit, DB, script

doc = revit.doc
output = script.get_output()


# --- helpers -------------------------------------------------------------
def eid_value(eid):
    # Revit 2025+ uses .Value (Int64); older uses .IntegerValue (Int32)
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def elem_name(el):
    # 1) explicit CLR Name getter — defeats IronPython's .Name overload ambiguity
    try:
        n = DB.Element.Name.__get__(el)
        if n:
            return n
    except Exception:
        pass
    # 2) fall back to the type-name parameters (covers odd system types)
    for bip in (DB.BuiltInParameter.ALL_MODEL_TYPE_NAME,
                DB.BuiltInParameter.SYMBOL_NAME_PARAM):
        try:
            p = el.get_Parameter(bip)
            if p and p.HasValue:
                v = p.AsString()
                if v:
                    return v
        except Exception:
            pass
    return u"<unnamed>"


# --- 1) count instances per type id -------------------------------------
instance_counts = {}
for inst in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
    tid = inst.GetTypeId()
    if tid is None or tid == DB.ElementId.InvalidElementId:
        continue
    key = eid_value(tid)
    instance_counts[key] = instance_counts.get(key, 0) + 1


# --- 2) walk all element types: CategoryType > Category > Family --------
# report = { ct_name: { cat_name: { family_name: [ (type_name, count) ] } } }
report = {}
for et in DB.FilteredElementCollector(doc).WhereElementIsElementType():
    cat = et.Category
    if cat is None:
        continue
    ct = cat.CategoryType
    if ct == DB.CategoryType.Model:
        ct_name = "Model"
    elif ct == DB.CategoryType.Annotation:
        ct_name = "Annotation"
    else:
        continue

    try:
        fam = et.FamilyName
    except Exception:
        fam = None
    if not fam:
        fam = u"(system / no family)"

    count = instance_counts.get(eid_value(et.Id), 0)

    report.setdefault(ct_name, {}) \
          .setdefault(cat.Name, {}) \
          .setdefault(fam, []) \
          .append((elem_name(et), count))


# --- 3) build report -----------------------------------------------------
BG = "#1E1E2E"; CARD = "#2A2A3C"; SURF = "#313244"
TXT = "#CDD6F4"; SUB = "#A6ADC8"; ACCENT = "#F0A500"
GREEN = "#A6E3A1"; RED = "#F38BA8"

body = []
grand_types = 0
grand_unused = 0
summary_rows = []

for ct_name in [c for c in ("Model", "Annotation") if c in report]:
    body.append('<h2 style="color:%s;margin:16px 0 4px;">%s Categories</h2>'
                % (ACCENT, ct_name))

    for cat_name in sorted(report[ct_name].keys(), key=lambda s: s.lower()):
        fams = report[ct_name][cat_name]
        cat_types = sum(len(t) for t in fams.values())
        cat_unused = sum(sum(1 for _, c in t if c == 0) for t in fams.values())
        grand_types += cat_types
        grand_unused += cat_unused
        summary_rows.append((ct_name, cat_name, cat_types, cat_unused))

        body.append('<div style="background:%s;border-radius:8px;'
                    'margin:6px 0;padding:8px 12px;">' % CARD)
        body.append('<div style="font-weight:bold;color:%s;font-size:14px;">'
                    '%s <span style="color:%s;font-weight:normal;">'
                    '&mdash; %d types, %d unused</span></div>'
                    % (TXT, cat_name, RED if cat_unused else SUB,
                       cat_types, cat_unused))

        for fam in sorted(fams.keys(), key=lambda s: s.lower()):
            # used first (alpha), then unused (alpha)
            tlist = sorted(fams[fam], key=lambda t: (t[1] == 0, t[0].lower()))
            fam_unused = sum(1 for _, c in tlist if c == 0)
            body.append('<div style="margin:6px 0 2px 6px;color:%s;">'
                        '<b>%s</b> <span style="color:%s;">'
                        '(%d types, %d unused)</span></div>'
                        % (SUB, fam, SUB, len(tlist), fam_unused))
            body.append('<ul style="margin:2px 0 6px 22px;padding:0;">')
            for tname, c in tlist:
                if c == 0:
                    body.append('<li style="color:%s;">%s &mdash; '
                                '<b>NOT USED</b></li>' % (RED, tname))
                else:
                    body.append('<li>%s &mdash; <span style="color:%s;">'
                                '%d instance%s</span></li>'
                                % (tname, GREEN, c, "" if c == 1 else "s"))
            body.append('</ul>')
        body.append('</div>')


# --- 4) summary header + table ------------------------------------------
head = ['<h1 style="color:%s;margin:0 0 6px;">Unused Type Report</h1>' % ACCENT]
head.append('<div style="color:%s;margin-bottom:10px;">Total types: '
            '<b>%d</b> &nbsp;|&nbsp; Unused types: '
            '<b style="color:%s;">%d</b></div>'
            % (SUB, grand_types, RED, grand_unused))
head.append('<table style="border-collapse:collapse;margin-bottom:10px;">')
head.append('<tr style="color:%s;text-align:left;">'
            '<th style="padding:4px 12px;">Kind</th>'
            '<th style="padding:4px 12px;">Category</th>'
            '<th style="padding:4px 12px;">Types</th>'
            '<th style="padding:4px 12px;">Unused</th></tr>' % ACCENT)
for ct_name, cat_name, ct, cu in summary_rows:
    head.append('<tr style="border-top:1px solid %s;">'
                '<td style="padding:3px 12px;color:%s;">%s</td>'
                '<td style="padding:3px 12px;">%s</td>'
                '<td style="padding:3px 12px;">%d</td>'
                '<td style="padding:3px 12px;color:%s;">%d</td></tr>'
                % (SURF, SUB, ct_name, cat_name, ct,
                   RED if cu else TXT, cu))
head.append('</table>')

html = ('<div style="background:%s;color:%s;padding:14px 18px;'
        'border-radius:12px;font-family:Segoe UI,Arial,sans-serif;'
        'font-size:13px;">%s%s</div>'
        % (BG, TXT, "".join(head), "".join(body)))

output.print_html(html)
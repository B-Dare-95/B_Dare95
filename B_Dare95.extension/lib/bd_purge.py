# -*- coding: utf-8 -*-
"""bd_purge - the shared window and the purge rules behind the Purge buttons.

One button per kind of content. Each button script only calls
    bd_purge.run(__revit__, "<kind>")
with one of the keys in KINDS (bottom of this file).

Every window (approved mockup):
  - a line saying what "unused" means for that kind
  - unused items listed and checked (nothing checked for Views, Sheets, Schedules,
    Analytical Models and CAD/PDF), search, All / None
  - "Show used items too": used items greyed out, can't be checked, with the reason
  - the window stays open; the list refreshes and the status bar reports the result
One Purge click is one undo. Warnings are never suppressed; a Revit error rolls back
only the transaction it came from (and that item is reported).

Put this file in B_Dare95.extension/lib/.
"""
from collections import Counter

import clr
clr.AddReference("RevitAPI")
clr.AddReference("System.Core")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import Autodesk.Revit.DB as DB
from System import EventHandler
from System.Collections.Generic import HashSet, List
from System.Windows import (Thickness, CornerRadius, VerticalAlignment, HorizontalAlignment, TextAlignment,
                            TextTrimming, Visibility, RoutedEventHandler)
from System.Windows.Controls import Border, DockPanel, Dock, CheckBox, TextBlock, StackPanel
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from pyrevit import forms

# IBM Carbon
BG, CARD, SURFACE, MUTED = "#161616", "#262626", "#393939", "#525252"
TEXT, SUBTEXT, ACCENT = "#F4F4F4", "#A8A8A8", "#F1C21B"


# =============================================================================
#  Helpers
# =============================================================================

def eid_int(eid):
    """ElementId as int: .Value (2024+) with .IntegerValue fallback."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def elem_name(e):
    try:
        return DB.Element.Name.GetValue(e) or u""
    except Exception:
        try:
            return e.Name or u""
        except Exception:
            return u"?"


def brush(hex_code):
    try:
        return SolidColorBrush(ColorConverter.ConvertFromString(hex_code))
    except Exception:
        return SolidColorBrush(ColorConverter.ConvertFromString("#8D8D8D"))


def plural(n, word, word_pl=None):
    return u"{0:,} {1}".format(n, word if n == 1 else (word_pl or word + u"s"))


def _param_text(e, bip):
    try:
        p = e.get_Parameter(bip)
        if p is None or not p.HasValue:
            return u""
        return p.AsValueString() or p.AsString() or u""
    except Exception:
        return u""


def _color_hex(color):
    """'#RRGGBB' from a Revit Color. Red / Green / Blue are .NET bytes; formatted as they are they
    gave a string WPF couldn't read ("Token is not valid"), so they go through int() first."""
    try:
        if color is not None and color.IsValid:
            return u"#{0:02X}{1:02X}{2:02X}".format(int(color.Red), int(color.Green), int(color.Blue))
    except Exception:
        pass
    return None


# =============================================================================
#  Revit's own Purge Unused list
# =============================================================================

def legend_ids(doc):
    """Types shown by legend components, and their families. Revit's purge counts them as
    unused, but deleting them removes the symbols from legend views on sheets."""
    ids = set()
    for comp in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_LegendComponents):
        try:
            p = comp.get_Parameter(DB.BuiltInParameter.LEGEND_COMPONENT)
            t = doc.GetElement(p.AsElementId()) if p is not None else None
        except Exception:
            t = None
        if t is not None:
            ids.add(eid_int(t.Id))
            if isinstance(t, DB.FamilySymbol):
                ids.add(eid_int(t.Family.Id))
    return ids


def revit_unused(doc):
    """{id int: ElementId} of what Revit's Purge Unused would delete now, minus legend symbols."""
    keep = legend_ids(doc)
    out = {}
    for i in doc.GetUnusedElements(HashSet[DB.ElementId]()):
        k = eid_int(i)
        if k not in keep:
            out[k] = i
    return out


# =============================================================================
#  Deleting (explicit Start / Commit, RollBack on failure only)
# =============================================================================

class _ErrorsRollBack(DB.IFailuresPreprocessor):
    """Errors roll the transaction back and are recorded. Warnings are left alone."""

    def __init__(self, sink):
        self.sink = sink

    def PreprocessFailures(self, accessor):
        for f in accessor.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Error:
                try:
                    self.sink.append(f.GetDescriptionText())
                except Exception:
                    self.sink.append(u"Revit error")
                return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _start(doc, name, sink):
    t = DB.Transaction(doc, name)
    t.Start()
    options = t.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(_ErrorsRollBack(sink))
    options.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(options)
    return t


class Result(object):
    def __init__(self):
        self.deleted = []      # names
        self.dependents = 0    # other elements Revit deleted with them
        self.kept = []         # (name, why) left in place on purpose
        self.failed = []       # (name, message)

    def merge(self, other):
        self.deleted.extend(other.deleted)
        self.dependents += other.dependents
        self.kept.extend(other.kept)
        self.failed.extend(other.failed)


def delete_elements(doc, items, title):
    """items: [(ElementId, name)]. One transaction for the batch; if Revit refuses the batch,
    one transaction per item so one bad item doesn't stop the rest."""
    result = Result()
    items = [(i, n) for i, n in items if doc.GetElement(i) is not None]
    if not items:
        return result
    errors = []
    t = _start(doc, title, errors)
    count = 0
    try:
        count = doc.Delete(List[DB.ElementId]([i for i, _ in items])).Count
        status = t.Commit()
    except Exception:
        if t.GetStatus() == DB.TransactionStatus.Started:
            t.RollBack()
        status = None
    if status == DB.TransactionStatus.Committed:
        result.deleted = [n for _, n in items]
        result.dependents = max(0, count - len(items))
        return result
    for eid, name in items:
        if doc.GetElement(eid) is None:
            continue
        errors = []
        t = _start(doc, title, errors)
        try:
            n = doc.Delete(eid).Count
            status = t.Commit()
        except Exception as ex:
            if t.GetStatus() == DB.TransactionStatus.Started:
                t.RollBack()
            result.failed.append((name, u"{}".format(ex)))
            continue
        if status == DB.TransactionStatus.Committed:
            result.deleted.append(name)
            result.dependents += max(0, n - 1)
        else:
            result.failed.append((name, errors[0] if errors else u"Revit rolled it back"))
    return result


def own_ids(category):
    """Ids a (sub)category takes with it when deleted: itself, its graphics styles, its subcategories."""
    ids = set([eid_int(category.Id)])
    for kind in (DB.GraphicsStyleType.Projection, DB.GraphicsStyleType.Cut):
        try:
            g = category.GetGraphicsStyle(kind)
            if g is not None:
                ids.add(eid_int(g.Id))
        except Exception:
            pass
    try:
        for s in category.SubCategories:
            ids |= own_ids(s)
    except Exception:
        pass
    return ids


def delete_styles(doc, items, title):
    """items: [(Category, name)]. Each style is deleted on its own and put back when Revit would
    take anything else with it (lines or elements moved off it = it was in use)."""
    result = Result()
    errors = []
    done = []
    t = _start(doc, title, errors)
    try:
        for cat, name in items:
            own = own_ids(cat)
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                gone = set(eid_int(i) for i in doc.Delete(cat.Id))
            except Exception as ex:
                if st.GetStatus() == DB.TransactionStatus.Started:
                    st.RollBack()
                result.failed.append((name, u"{}".format(ex)))
                continue
            if gone - own:
                st.RollBack()
                result.kept.append((name, u"in use: {} other elements would go with it".format(len(gone - own))))
            else:
                st.Commit()
                done.append(name)
        status = t.Commit()
    except Exception as ex:
        if t.GetStatus() == DB.TransactionStatus.Started:
            t.RollBack()
        result.failed.append((u"(all)", u"{}".format(ex)))
        return result
    if status == DB.TransactionStatus.Committed:
        result.deleted = done
    else:
        result.failed.extend((n, errors[0] if errors else u"Revit rolled it back") for n in done)
    return result


def referenced_ids(doc):
    """Ids that types and reference planes point at through a parameter (a wall sweep type's
    subcategory, a reference plane's subcategory). Only categorized types and reference planes:
    reading ElementId parameters of every element can crash Revit on some internal elements."""
    ids = set()
    elements = list(DB.FilteredElementCollector(doc).WhereElementIsElementType()) + \
        list(DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane))
    for e in elements:
        try:
            if e.Category is None:
                continue
            for p in e.Parameters:
                if p.StorageType == DB.StorageType.ElementId and p.HasValue:
                    ids.add(eid_int(p.AsElementId()))
        except Exception:
            pass
    return ids


# =============================================================================
#  Tools: what one window lists and how it deletes
# =============================================================================

def row(key, name, cells, unused, status=None, eid=None, swatch=None, tickable=None):
    return {"key": key, "name": name or u"(no name)", "cells": [u"{}".format(c) for c in cells],
            "unused": unused, "status": status or (u"Unused" if unused else u"Used"),
            "eid": eid, "swatch": swatch,
            "tickable": unused if tickable is None else tickable}


class Tool(object):
    """title: the kind ("Line Styles"); noun: one item ("line style")
    columns: [(header, width)] after the name; info: what "unused" means
    apply(keys) -> Result
    default_tick: unused rows start checked; lists_all: every row is a candidate (no used/unused)"""

    def __init__(self, title, noun, info, columns, rows, apply, default_tick=True, lists_all=False,
                 noun_plural=None):
        self.title = title
        self.noun = noun
        self.noun_plural = noun_plural or noun + u"s"
        self.info = info
        self.columns = columns
        self.rows = rows
        self.apply = apply
        self.default_tick = default_tick
        self.lists_all = lists_all

    def unused_keys(self):
        return [r["key"] for r in self.rows if r["tickable"]]


def _delete_rows(doc, rows, keys, title):
    keys = set(keys)
    return delete_elements(doc, [(r["eid"], r["name"]) for r in rows if r["key"] in keys], title)


# ---------------------------------------------------------------- types Revit's purge knows
def _type_tool(doc, cls, title, noun, info, columns, cells_of, swatch_of=None, default_tick=True):
    unused = revit_unused(doc)
    rows = []
    for e in DB.FilteredElementCollector(doc).OfClass(cls):
        if isinstance(e, DB.DimensionType):
            try:
                if e.StyleType is None:
                    continue
            except Exception:
                continue
        k = eid_int(e.Id)
        rows.append(row(k, elem_name(e), cells_of(e), k in unused, eid=e.Id,
                        swatch=swatch_of(e) if swatch_of else None))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(title, noun, info, columns, rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge " + title), default_tick=default_tick)


def text_styles(doc, cache):
    return _type_tool(
        doc, DB.TextNoteType, u"Text Styles", u"text style",
        u"A text style is unused when no text note uses it - Revit's own Purge Unused rule.",
        [(u"Font", 130), (u"Size", 80)],
        lambda e: [_param_text(e, DB.BuiltInParameter.TEXT_FONT), _param_text(e, DB.BuiltInParameter.TEXT_SIZE)])


def dimension_styles(doc, cache):
    return _type_tool(
        doc, DB.DimensionType, u"Dimension Styles", u"dimension style",
        u"A dimension style is unused when no dimension uses it - Revit's own Purge Unused rule.",
        [(u"Kind", 140)], lambda e: [u"{}".format(e.StyleType)])


def line_patterns(doc, cache):
    return _type_tool(
        doc, DB.LinePatternElement, u"Line Patterns", u"line pattern",
        u"A line pattern is unused when no line style, object style, override or type uses it - "
        u"Revit's own Purge Unused rule.", [], lambda e: [])


def fill_patterns(doc, cache):
    def target(e):
        try:
            return u"{}".format(e.GetFillPattern().Target)
        except Exception:
            return u""
    return _type_tool(
        doc, DB.FillPatternElement, u"Fill Patterns", u"fill pattern",
        u"A fill pattern is unused when no material, filled region, override or type uses it - "
        u"Revit's own Purge Unused rule.", [(u"Kind", 90)], lambda e: [target(e)])


def filled_region_types(doc, cache):
    def pattern(e):
        try:
            p = doc.GetElement(e.ForegroundPatternId)
            return elem_name(p) if p is not None else u""
        except Exception:
            return u""

    def color(e):
        try:
            return _color_hex(e.ForegroundPatternColor)
        except Exception:
            return None
    return _type_tool(
        doc, DB.FilledRegionType, u"Filled Region Types", u"filled region type",
        u"A filled region type is unused when no filled region uses it - Revit's own Purge Unused rule.",
        [(u"Foreground pattern", 160)], lambda e: [pattern(e)], swatch_of=color)


def materials(doc, cache):
    def mclass(e):
        try:
            return e.MaterialClass or u""
        except Exception:
            return u""

    def color(e):
        try:
            return _color_hex(e.Color)
        except Exception:
            return None
    return _type_tool(
        doc, DB.Material, u"Materials", u"material",
        u"A material is unused when no element, type, family or other material uses it - Revit's own "
        u"Purge Unused rule. Its appearance assets go with it when nothing else uses them.",
        [(u"Class", 120)], lambda e: [mclass(e)], swatch_of=color)


# ---------------------------------------------------------------- styles (subcategories)
def line_styles(doc, cache):
    curves = Counter()
    for c in DB.FilteredElementCollector(doc).OfClass(DB.CurveElement):
        try:
            curves[eid_int(c.LineStyle.Id)] += 1
        except Exception:
            pass
    refs = referenced_ids(doc)
    projection = DB.GraphicsStyleType.Projection
    rows, cats = [], {}
    lines = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    for s in lines.SubCategories:
        k = eid_int(s.Id)
        if k < 0:
            continue  # Revit's own styles can't be deleted
        g = s.GetGraphicsStyle(projection)
        count = curves[eid_int(g.Id)] if g is not None else 0
        by_type = bool(own_ids(s) & refs)
        unused = not count and not by_type
        try:
            pattern = doc.GetElement(s.GetLinePatternId(projection))
            pattern_name = elem_name(pattern) if pattern is not None else u"Solid"
        except Exception:
            pattern_name = u""
        weight = s.GetLineWeight(projection) or u""
        status = u"Unused" if unused else (u"Used" if count else u"Used by a type")
        rows.append(row(k, s.Name, [u"{} · {}".format(pattern_name, weight), count], unused, status,
                        swatch=_color_hex(s.LineColor)))
        cats[k] = s
    rows.sort(key=lambda r: r["name"].lower())

    def apply(keys):
        return delete_styles(doc, [(cats[k], cats[k].Name) for k in keys if k in cats], u"Purge Line Styles")
    return Tool(u"Line Styles", u"line style",
                u"A line style is unused when no line in the model uses it and no type points to it. Revit's "
                u"own styles are never listed. Each one is deleted on its own and put back if anything else "
                u"would go with it.", [(u"Pattern · weight", 140), (u"Lines", 60)], rows, apply)


_CAD_EXT = (u".dwg", u".dxf", u".dgn", u".sat", u".skp", u".3dm", u".ifc")


def _family_styles(doc):
    """(defined (category, subcategory) names, locked category names) from every family.
    Opens each editable family; in-place and locked families lock their whole category."""
    defined, locked = set(), set()
    fams = list(DB.FilteredElementCollector(doc).OfClass(DB.Family))
    with forms.ProgressBar(title=u"Reading families for their object styles ({value} of {max_value})",
                           cancellable=True) as pb:
        for n, fam in enumerate(fams, 1):
            if pb.cancelled:
                return None
            pb.update_progress(n, len(fams))
            fdoc = None
            try:
                if not fam.IsInPlace and fam.IsEditable:
                    fdoc = doc.EditFamily(fam)
            except Exception:
                fdoc = None
            if fdoc is None:
                if fam.FamilyCategory is not None:
                    locked.add(fam.FamilyCategory.Name)
                continue
            try:
                for c in fdoc.Settings.Categories:
                    try:
                        for s in c.SubCategories:
                            defined.add((c.Name, s.Name))
                    except Exception:
                        pass
            finally:
                fdoc.Close(False)
    return defined, locked


def _linked_subcategories(doc):
    pairs, unknown = set(), False
    for t in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType):
        try:
            if u"{}".format(t.GetLinkedFileStatus()) != u"Loaded":
                unknown = True
        except Exception:
            unknown = True
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        try:
            ldoc = inst.GetLinkDocument()
        except Exception:
            ldoc = None
        if ldoc is None:
            continue
        for c in ldoc.Settings.Categories:
            try:
                for s in c.SubCategories:
                    pairs.add((c.Name, s.Name))
            except Exception:
                pass
    return pairs, unknown


def object_styles(doc, cache):
    if "families" not in cache:
        read = _family_styles(doc)
        if read is None:
            return None  # cancelled
        cache["families"] = read
    defined, locked = cache["families"]
    refs = referenced_ids(doc)
    in_links, links_unknown = _linked_subcategories(doc)
    imported = set()
    for i in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance):
        try:
            if i.Category is not None:
                imported.add(eid_int(i.Category.Id))
        except Exception:
            pass
    lines_id = eid_int(doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines).Id)

    rows, cats = [], {}
    for c in doc.Settings.Categories:
        try:
            if c.CategoryType not in (DB.CategoryType.Model, DB.CategoryType.Annotation):
                continue
            cid = eid_int(c.Id)
            if cid == lines_id or cid in imported or c.Name.lower().endswith(_CAD_EXT):
                continue
            subs = list(c.SubCategories)
        except Exception:
            continue
        for s in subs:
            k = eid_int(s.Id)
            if k < 0:
                continue
            why = None
            if (c.Name, s.Name) in defined:
                why = u"Used by families"
            elif c.Name in locked:
                why = u"Category has in-place or locked families"
            elif (c.Name, s.Name) in in_links:
                why = u"Used in a link"
            elif links_unknown:
                why = u"A link is not loaded"
            elif own_ids(s) & refs:
                why = u"Used by a type"
            rows.append(row(k, s.Name, [c.Name], why is None, why, swatch=_color_hex(s.LineColor)))
            cats[k] = s
    rows.sort(key=lambda r: (r["cells"][0].lower(), r["name"].lower()))

    def apply(keys):
        return delete_styles(doc, [(cats[k], cats[k].Name) for k in keys if k in cats], u"Purge Object Styles")
    return Tool(u"Object Styles", u"object style",
                u"A subcategory is unused when no loaded family defines it, no type points to it and no loaded "
                u"link uses it. Categories with in-place or locked families are left alone, and nothing is "
                u"listed as unused while a link is unloaded. Each one is deleted on its own and put back if "
                u"anything else would go with it.", [(u"Category", 180)], rows, apply)


# ---------------------------------------------------------------- parameters
DELETABLE_PARAMS = (u"Project", u"Shared", u"Global")


def _rule_param_ids(f):
    out = []
    if isinstance(f, DB.ElementLogicalFilter):
        for sub in f.GetFilters():
            out.extend(_rule_param_ids(sub))
    elif isinstance(f, DB.ElementParameterFilter):
        for r in f.GetRules():
            try:
                out.append(eid_int(r.GetRuleParameter()))
            except Exception:
                pass
    return out


def parameters(doc, cache):
    bound = {}
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        try:
            bound[eid_int(it.Key.Id)] = u"Instance" if isinstance(it.Current, DB.InstanceBinding) else u"Type"
        except Exception:
            pass
    valued = Counter()
    for collector in (DB.FilteredElementCollector(doc).WhereElementIsNotElementType(),
                      DB.FilteredElementCollector(doc).WhereElementIsElementType()):
        for e in collector:
            try:
                params = list(e.Parameters)
            except Exception:
                continue
            for p in params:
                try:
                    pid = eid_int(p.Id)
                    if pid <= 0 or not p.HasValue:
                        continue
                    st = p.StorageType
                    if (st == DB.StorageType.String and p.AsString()) or \
                            (st == DB.StorageType.ElementId and eid_int(p.AsElementId()) > 0) or \
                            st in (DB.StorageType.Integer, DB.StorageType.Double):
                        valued[pid] += 1
                except Exception:
                    pass
    in_schedules = Counter()
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            d = vs.Definition
            for i in range(d.GetFieldCount()):
                in_schedules[eid_int(d.GetField(i).ParameterId)] += 1
        except Exception:
            pass
    in_filters = Counter()
    for pf in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement):
        try:
            ef = pf.GetElementFilter()
            if ef is not None:
                for pid in _rule_param_ids(ef):
                    in_filters[pid] += 1
        except Exception:
            pass
    global_formulas = []
    for g in DB.FilteredElementCollector(doc).OfClass(DB.GlobalParameter):
        try:
            if g.IsDrivenByFormula:
                global_formulas.append((eid_int(g.Id), g.GetFormula() or u""))
        except Exception:
            pass

    rows = []
    for pe in DB.FilteredElementCollector(doc).OfClass(DB.ParameterElement):
        pid = eid_int(pe.Id)
        name = elem_name(pe)
        if isinstance(pe, DB.GlobalParameter):
            kind = u"Global"
            try:
                valued[pid] += pe.GetAffectedElements().Count
            except Exception:
                pass
            if any(gid != pid and name in text for gid, text in global_formulas):
                valued[pid] += 1
        elif isinstance(pe, DB.SharedParameterElement):
            kind = u"Shared" if pid in bound else u"Shared (families only)"
        else:
            if pid not in bound:
                continue  # Revit's own (electrical load classifications and the like)
            kind = u"Project"
        used_by = valued[pid] or in_schedules[pid] or in_filters[pid]
        if kind == u"Shared (families only)":
            status, unused = u"Comes with families", False
        else:
            unused = not used_by
            status = u"Unused" if unused else u"Used"
        rows.append(row(pid, name, [kind, valued[pid], in_schedules[pid], in_filters[pid]], unused, status,
                        eid=pe.Id))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(u"Parameters", u"parameter",
                u"A project, shared or global parameter is unused when no element or type has a value in it and "
                u"no schedule or view filter uses it. Shared parameters that only families carry come back with "
                u"those families, so they're never listed as unused.",
                [(u"Kind", 120), (u"With value", 76), (u"Schedules", 72), (u"Filters", 56)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge Parameters"))


# ---------------------------------------------------------------- views and sheets
def view_filters(doc, cache):
    views, templates = Counter(), Counter()
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            ids = v.GetFilters()
        except Exception:
            continue
        for fid in ids:
            (templates if v.IsTemplate else views)[eid_int(fid)] += 1
    rows = []
    for f in DB.FilteredElementCollector(doc).OfClass(DB.FilterElement):
        k = eid_int(f.Id)
        kind = u"Selection" if isinstance(f, DB.SelectionFilterElement) else u"Rule-based"
        unused = not views[k] and not templates[k]
        rows.append(row(k, elem_name(f), [kind, views[k], templates[k]], unused, eid=f.Id))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(u"View Filters", u"view filter",
                u"A view filter is unused when no view and no view template applies it.",
                [(u"Kind", 90), (u"Views", 56), (u"Templates", 72)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge View Filters"))


def view_templates(doc, cache):
    used = Counter()
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            if not v.IsTemplate and eid_int(v.ViewTemplateId) > 0:
                used[eid_int(v.ViewTemplateId)] += 1
        except Exception:
            pass
    defaults = set()
    for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        try:
            defaults.add(eid_int(t.DefaultTemplateId))
        except Exception:
            pass
    rows = []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if not v.IsTemplate:
            continue
        k = eid_int(v.Id)
        is_default = k in defaults
        unused = not used[k] and not is_default
        status = u"Unused" if unused else (u"Used" if used[k] else u"Default of a view type")
        rows.append(row(k, v.Name, [u"{}".format(v.ViewType), used[k]], unused, status, eid=v.Id))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(u"View Templates", u"view template",
                u"A view template is unused when no view uses it and no view type applies it to new views.",
                [(u"View type", 120), (u"Views", 56)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge View Templates"))


def _placed_view_ids(doc):
    ids = set(eid_int(vp.ViewId) for vp in DB.FilteredElementCollector(doc).OfClass(DB.Viewport))
    ids |= set(eid_int(s.ScheduleId) for s in DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance))
    return ids


_SKIP_VIEW_TYPES = ("ProjectBrowser", "SystemBrowser", "Undefined", "Internal", "DrawingSheet", "Schedule",
                    "PanelSchedule", "ColumnSchedule")


def views(doc, cache):
    placed = _placed_view_ids(doc)
    parents = set()
    all_views = list(DB.FilteredElementCollector(doc).OfClass(DB.View))
    for v in all_views:
        try:
            primary = eid_int(v.GetPrimaryViewId())
            if primary > 0 and eid_int(v.Id) in placed:
                parents.add(primary)
        except Exception:
            pass
    protected = {}
    if cache.get("active") is not None:
        protected[cache["active"]] = u"Open view"
    try:
        start = DB.StartingViewSettings.GetStartingViewSettings(doc).ViewId
        if eid_int(start) > 0:
            protected[eid_int(start)] = u"Starting view"
    except Exception:
        pass
    rows = []
    for v in all_views:
        try:
            if v.IsTemplate or isinstance(v, DB.ViewSchedule) or u"{}".format(v.ViewType) in _SKIP_VIEW_TYPES:
                continue
        except Exception:
            continue
        k = eid_int(v.Id)
        if k in placed:
            status = u"On a sheet"
        elif k in parents:
            status = u"Its dependent is on a sheet"
        elif k in protected:
            status = protected[k]
        else:
            status = u"On no sheet"
        unused = status == u"On no sheet"
        rows.append(row(k, v.Name, [u"{}".format(v.ViewType)], unused, status, eid=v.Id))
    rows.sort(key=lambda r: (r["cells"][0], r["name"].lower()))
    return Tool(u"Views", u"view",
                u"Views on no sheet. Nothing is checked for you: working and coordination views often live off "
                u"sheets on purpose. Views whose dependent is on a sheet, the open view and the starting view "
                u"are kept. Deleting a view also deletes what is drawn only in it.",
                [(u"View type", 130)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge Views"), default_tick=False)


def sheets(doc, cache):
    filled = Counter()
    for vp in DB.FilteredElementCollector(doc).OfClass(DB.Viewport):
        filled[eid_int(vp.SheetId)] += 1
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance):
        try:
            if not s.IsTitleblockRevisionSchedule:
                filled[eid_int(s.OwnerViewId)] += 1
        except Exception:
            pass
    rows = []
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
        try:
            if s.IsPlaceholder:
                continue
        except Exception:
            pass
        k = eid_int(s.Id)
        unused = filled[k] == 0
        rows.append(row(k, u"{} - {}".format(s.SheetNumber, s.Name), [filled[k]], unused,
                        u"Empty" if unused else u"Has views", eid=s.Id))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(u"Sheets", u"sheet",
                u"Sheets with no view and no schedule on them (the title block's revision schedule doesn't "
                u"count). Nothing is checked for you: an empty sheet can be a placeholder in a sheet list.",
                [(u"Views on it", 80)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge Sheets"), default_tick=False)


def schedules(doc, cache):
    placed = _placed_view_ids(doc)
    rows = []
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if s.IsTemplate or s.IsTitleblockRevisionSchedule or getattr(s, "IsInternalKeynoteSchedule", False):
                continue
        except Exception:
            continue
        k = eid_int(s.Id)
        try:
            is_key = s.Definition.IsKeySchedule
        except Exception:
            is_key = False
        if k in placed:
            status = u"On a sheet"
        elif is_key:
            status = u"Key schedule"
        else:
            status = u"On no sheet"
        unused = status == u"On no sheet"
        rows.append(row(k, s.Name, [u"Key" if is_key else u"Regular"], unused, status, eid=s.Id))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(u"Schedules", u"schedule",
                u"Schedules placed on no sheet. Nothing is checked for you: working schedules are often kept off "
                u"sheets. Key schedules are kept, because deleting one clears the key values on elements.",
                [(u"Kind", 80)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge Schedules"), default_tick=False)


# ---------------------------------------------------------------- datums
def scope_boxes(doc, cache):
    def assigned(elements, bip, into):
        for e in elements:
            try:
                p = e.get_Parameter(bip)
                if p is not None and p.HasValue and eid_int(p.AsElementId()) > 0:
                    into[eid_int(p.AsElementId())] += 1
            except Exception:
                pass
    in_views, in_datums = Counter(), Counter()
    assigned([v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if not v.IsTemplate],
             DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP, in_views)
    for cls in (DB.Level, DB.Grid, DB.ReferencePlane):
        assigned(DB.FilteredElementCollector(doc).OfClass(cls), DB.BuiltInParameter.DATUM_VOLUME_OF_INTEREST,
                 in_datums)
    rows = []
    for box in (DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)
                .WhereElementIsNotElementType()):
        k = eid_int(box.Id)
        unused = not in_views[k] and not in_datums[k]
        rows.append(row(k, elem_name(box), [in_views[k], in_datums[k]], unused, eid=box.Id))
    rows.sort(key=lambda r: r["name"].lower())
    return Tool(u"Scope Boxes", u"scope box",
                u"A scope box is unused when no view's crop and no level, grid or reference plane is assigned "
                u"to it.", [(u"Views", 56), (u"Datums", 60)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge Scope Boxes"), noun_plural=u"scope boxes")


_LEVEL_PARAMS = ("WALL_BASE_CONSTRAINT", "WALL_HEIGHT_TYPE", "FAMILY_LEVEL_PARAM", "FAMILY_BASE_LEVEL_PARAM",
                 "FAMILY_TOP_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM", "LEVEL_PARAM", "STAIRS_BASE_LEVEL_PARAM",
                 "STAIRS_TOP_LEVEL_PARAM", "STAIRS_RAILING_BASE_LEVEL_PARAM", "ROOM_LEVEL_ID", "ROOM_UPPER_LEVEL",
                 "RBS_START_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM", "SCHEDULE_BASE_LEVEL_PARAM",
                 "SCHEDULE_TOP_LEVEL_PARAM", "ROOF_BASE_LEVEL_PARAM", "ROOF_CONSTRAINT_LEVEL_PARAM",
                 "CEILING_LEVEL_PARAM", "STRUCTURAL_REFERENCE_LEVEL_ELEVATION", "VIEW_UNDERLAY_BOTTOM_ID",
                 "STRUCTURAL_BEAM_END0_ELEVATION")


def levels(doc, cache):
    lvls = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.Elevation)
    level_ids = set(eid_int(l.Id) for l in lvls)
    by_name = dict((l.Name, eid_int(l.Id)) for l in lvls)
    bips = [getattr(DB.BuiltInParameter, n) for n in _LEVEL_PARAMS if hasattr(DB.BuiltInParameter, n)]
    on_level = Counter()
    for e in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
        try:
            if e.Category is None or isinstance(e, (DB.View, DB.Level)):
                continue
            lid = eid_int(e.LevelId) if e.LevelId is not None else -1
            if lid in level_ids:
                on_level[lid] += 1
                continue
            host = getattr(e, "Host", None)
            if isinstance(host, DB.Level):
                on_level[eid_int(host.Id)] += 1
                continue
            if isinstance(e, DB.CurveElement) and e.SketchPlane is not None and e.SketchPlane.Name in by_name:
                on_level[by_name[e.SketchPlane.Name]] += 1
                continue
            for bip in bips:
                p = e.get_Parameter(bip)
                if p is not None and p.StorageType == DB.StorageType.ElementId and p.HasValue:
                    rid = eid_int(p.AsElementId())
                    if rid in level_ids:
                        on_level[rid] += 1
        except Exception:
            pass
    plans = Counter()
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan):
        try:
            if not v.IsTemplate and v.GenLevel is not None:
                plans[eid_int(v.GenLevel.Id)] += 1
        except Exception:
            pass
    rows = []
    for l in lvls:
        k = eid_int(l.Id)
        if on_level[k]:
            status = u"Has elements"
        elif plans[k]:
            status = u"Has plan views"
        else:
            status = u"Unused"
        unused = status == u"Unused"
        rows.append(row(k, l.Name, [u"{:.3f}".format(l.Elevation * 0.3048), on_level[k], plans[k]], unused, status,
                        eid=l.Id))
    if rows and all(r["unused"] for r in rows):  # a model needs at least one level
        rows[0]["unused"] = rows[0]["tickable"] = False
        rows[0]["status"] = u"Last level kept"
    return Tool(u"Levels", u"level",
                u"A level is unused when nothing is placed on it, hosted by it or constrained to it, and it has no "
                u"plan views (deleting a level also deletes its plans).",
                [(u"Elevation (m)", 92), (u"Elements", 70), (u"Plans", 50)], rows,
                lambda keys: _delete_rows(doc, rows, keys, u"Purge Levels"))


# ---------------------------------------------------------------- analytical and CAD / PDF
# The structural analytical elements a user models (Revit 2023+). Analytical nodes, links, loads and
# boundary conditions on them go with them; energy-analysis spaces and surfaces are Revit's own and are
# never touched (deleting every element of the "analytical" categories, as Revitaal does, crashed Revit).
_ANALYTICAL = (("AnalyticalOpening", u"Analytical openings"),
               ("AnalyticalPanel", u"Analytical panels"),
               ("AnalyticalMember", u"Analytical members"))


def _analytical_class(name):
    return getattr(DB.Structure, name, None) or getattr(DB, name, None)


def analytical_models(doc, cache):
    rows, ids = [], {}
    for n, (cls_name, label) in enumerate(_ANALYTICAL, 1):
        cls = _analytical_class(cls_name)
        if cls is None:
            continue
        try:
            found = list(DB.FilteredElementCollector(doc).OfClass(cls).WhereElementIsNotElementType().ToElementIds())
        except Exception:
            continue
        if found:
            ids[n] = found
            rows.append(row(n, label, [len(found)], True, u"Analytical"))

    def apply(keys):
        result = Result()
        for n in sorted(keys):  # openings, then panels, then members: each kind in its own transaction
            label = [r["name"] for r in rows if r["key"] == n][0]
            result.merge(delete_elements(doc, [(i, label) for i in ids.get(n, [])], u"Purge " + label))
        return result
    return Tool(u"Analytical Models", u"analytical element type",
                u"Every analytical member, panel and opening in the model - not only unused ones. They aren't "
                u"needed for the physical model; the analytical nodes, links, loads and boundary conditions on them "
                u"go with them. Energy-analysis spaces and surfaces and the load cases, natures and combinations are "
                u"kept. Nothing is checked for you.",
                [(u"Elements", 70)], rows, apply, default_tick=False, lists_all=True)


def cad_and_pdf(doc, cache):
    rows, instances_of = [], {}
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance):
        try:
            t = doc.GetElement(inst.GetTypeId())
            kind = u"Link" if inst.IsLinked else u"Import"
            view = doc.GetElement(inst.OwnerViewId) if eid_int(inst.OwnerViewId) > 0 else None
            k = eid_int(inst.Id)
            rows.append(row(k, elem_name(t) if t is not None else u"CAD", [kind, elem_name(view) if view else u"Model"],
                            True, kind, eid=inst.Id))
            if t is not None:
                instances_of.setdefault(eid_int(t.Id), (t.Id, []))[1].append(k)
        except Exception:
            pass
    image_cls = getattr(DB, "ImageInstance", None)
    if image_cls is not None:
        for inst in DB.FilteredElementCollector(doc).OfClass(image_cls):
            try:
                t = doc.GetElement(inst.GetTypeId())
                if t is None or not (t.Path or u"").lower().endswith(u".pdf"):
                    continue
                view = doc.GetElement(inst.OwnerViewId)
                k = eid_int(inst.Id)
                rows.append(row(k, elem_name(t), [u"PDF", elem_name(view) if view else u""], True, u"PDF",
                                eid=inst.Id))
                instances_of.setdefault(eid_int(t.Id), (t.Id, []))[1].append(k)
            except Exception:
                pass
    for t in DB.FilteredElementCollector(doc).OfClass(DB.CADLinkType):
        k = eid_int(t.Id)
        if k not in instances_of:
            rows.append(row(k, elem_name(t), [u"Link type", u"Not placed"], True, u"Not placed", eid=t.Id))
    rows.sort(key=lambda r: (r["cells"][0], r["name"].lower()))

    def apply(keys):
        ticked = set(keys)
        items = [(r["eid"], r["name"]) for r in rows if r["key"] in ticked]
        # a type goes too once all its placed copies are checked, so a link is removed, not just hidden
        for tid, (type_id, insts) in instances_of.items():
            if insts and all(i in ticked for i in insts):
                t = doc.GetElement(type_id)
                items.append((type_id, (elem_name(t) if t is not None else u"") + u" (type)"))
        return delete_elements(doc, items, u"Purge CAD and PDF Files")
    return Tool(u"CAD and PDF Files", u"CAD or PDF file",
                u"Every CAD import, CAD link and PDF placed in the project, plus CAD links that aren't placed - not "
                u"only unused ones. When every placed copy of a file is checked, the file itself is removed too. "
                u"Nothing is checked for you.",
                [(u"Kind", 80), (u"View", 160)], rows, apply, default_tick=False, lists_all=True,
                noun_plural=u"CAD and PDF files")


KINDS = {
    "parameters": parameters,
    "text_styles": text_styles,
    "dimension_styles": dimension_styles,
    "line_styles": line_styles,
    "line_patterns": line_patterns,
    "fill_patterns": fill_patterns,
    "filled_region_types": filled_region_types,
    "materials": materials,
    "object_styles": object_styles,
    "view_filters": view_filters,
    "view_templates": view_templates,
    "views": views,
    "sheets": sheets,
    "schedules": schedules,
    "scope_boxes": scope_boxes,
    "levels": levels,
    "analytical_models": analytical_models,
    "cad_and_pdf": cad_and_pdf,
}


# =============================================================================
#  The window
# =============================================================================

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Purge" Width="760" SizeToContent="Height" MaxHeight="940"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="#161616" FontFamily="Segoe UI">
  <Window.Resources>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="8"/>
      <Setter Property="Padding" Value="14,12"/>
      <Setter Property="Margin" Value="0,0,0,8"/>
    </Style>
    <Style x:Key="Hint" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style x:Key="Input" TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style x:Key="Secondary" TargetType="Button">
      <Setter Property="Background" Value="#525252"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="MinWidth" Value="64"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}" CornerRadius="6" Padding="12,4">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Primary" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="MinWidth" Value="100"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}" CornerRadius="6" Padding="16,6">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>
  <StackPanel Margin="20">
    <TextBlock x:Name="TbTitle" Foreground="#F4F4F4" FontSize="16" FontWeight="Bold"/>
    <TextBlock x:Name="TbSub" Style="{StaticResource Hint}" Margin="0,2,0,12"/>

    <Border Style="{StaticResource Card}">
      <TextBlock x:Name="TbInfo" Style="{StaticResource Hint}" FontSize="12"/>
    </Border>

    <Border Style="{StaticResource Card}">
      <StackPanel>
        <DockPanel Margin="0,0,0,8">
          <Button x:Name="BtnNone" DockPanel.Dock="Right" Content="None" Style="{StaticResource Secondary}" Margin="6,0,0,0"/>
          <Button x:Name="BtnAll" DockPanel.Dock="Right" Content="All" Style="{StaticResource Secondary}"/>
          <CheckBox x:Name="ChkUsed" DockPanel.Dock="Right" Content="Show used items too" Margin="10,0,10,0"
                    VerticalAlignment="Center"/>
          <Grid>
            <TextBox x:Name="SearchBox" Style="{StaticResource Input}" Height="30"/>
            <TextBlock x:Name="SearchHint" Text="Search..." Foreground="#6F6F6F" FontSize="12"
                       Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
          </Grid>
        </DockPanel>
        <DockPanel x:Name="HeaderRow" Margin="34,0,10,4"/>
        <ScrollViewer MaxHeight="420" VerticalScrollBarVisibility="Auto">
          <StackPanel x:Name="ListPanel"/>
        </ScrollViewer>
        <TextBlock x:Name="TbEmpty" Style="{StaticResource Hint}" Margin="4,8,0,0" Visibility="Collapsed"/>
        <TextBlock x:Name="TbCount" Style="{StaticResource Hint}" Margin="0,8,0,0"/>
      </StackPanel>
    </Border>

    <Border x:Name="BdStatus" Background="#262626" CornerRadius="6" Padding="10,8" Margin="0,0,0,10">
      <TextBlock x:Name="TbStatus" Foreground="#A8A8A8" FontSize="12" TextWrapping="Wrap"/>
    </Border>

    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="BtnClose" Content="Close" Style="{StaticResource Secondary}" Height="34" MinWidth="88" Margin="0,0,10,0"/>
      <Button x:Name="BtnPurge" Content="Purge" Style="{StaticResource Primary}"/>
    </StackPanel>
  </StackPanel>
</Window>
"""

STATUS = {"info": ("#262626", "#A8A8A8"), "ok": ("#0E2A18", "#A7F0BA"), "warn": ("#3A2E06", "#FDDC69")}
PILL = {"unused": ("#3A2E06", "#FDDC69"), "used": ("#2E2E2E", "#A8A8A8"), "all": ("#393939", "#C6C6C6")}


class PurgeWindow(object):
    def __init__(self, uiapp, doc, kind, factory, tool, cache):
        self.uiapp = uiapp
        self.doc = doc
        self.kind = kind
        self.factory = factory
        self.tool = tool
        self.cache = cache
        self.rows = []  # (row, border, box)
        w = XamlReader.Parse(XAML)
        self.w = w
        self.ui = dict((n, w.FindName(n)) for n in (
            "TbTitle", "TbSub", "TbInfo", "BtnNone", "BtnAll", "ChkUsed", "SearchBox", "SearchHint", "HeaderRow",
            "ListPanel", "TbEmpty", "TbCount", "BdStatus", "TbStatus", "BtnClose",
            "BtnPurge"))
        try:
            WindowInteropHelper(w).Owner = uiapp.MainWindowHandle
        except Exception:
            pass
        ui = self.ui
        w.Title = u"Purge: {}".format(tool.title)
        ui["TbTitle"].Text = u"Purge: {}".format(tool.title)
        ui["TbInfo"].Text = tool.info
        if tool.lists_all:
            ui["ChkUsed"].Visibility = Visibility.Collapsed
        self._header()

        ui["SearchBox"].TextChanged += self._on_search
        ui["ChkUsed"].Click += RoutedEventHandler(self._on_filter)
        ui["BtnAll"].Click += RoutedEventHandler(self._on_all)
        ui["BtnNone"].Click += RoutedEventHandler(self._on_none)
        ui["BtnClose"].Click += RoutedEventHandler(self._on_close)
        ui["BtnPurge"].Click += RoutedEventHandler(self._on_purge)
        self._fill(first=True)
        self._status(u"Check what to purge, then click Purge. The list stays open and refreshes afterwards.")

    # ------------------------------------------------------------- list
    def _cell(self, text, width, color=SUBTEXT, align=TextAlignment.Right):
        tb = TextBlock()
        tb.Text = text
        tb.Width = width
        tb.FontSize = 11
        tb.Foreground = brush(color)
        tb.TextAlignment = align
        tb.TextTrimming = TextTrimming.CharacterEllipsis
        tb.VerticalAlignment = VerticalAlignment.Center
        tb.Margin = Thickness(8, 0, 0, 0)
        return tb

    def _header(self):
        dp = self.ui["HeaderRow"]
        status = self._cell(u"Status", 120)
        DockPanel.SetDock(status, Dock.Right)
        dp.Children.Add(status)
        for header, width in reversed(self.tool.columns):
            c = self._cell(header, width)
            DockPanel.SetDock(c, Dock.Right)
            dp.Children.Add(c)
        name = self._cell(u"Name", 100, align=TextAlignment.Left)
        name.Width = float("nan")
        dp.Children.Add(name)

    def _pill(self, r):
        kind = "all" if self.tool.lists_all else ("unused" if r["tickable"] else "used")
        bg, fg = PILL[kind]
        b = Border()
        b.Background = brush(bg)
        b.CornerRadius = CornerRadius(8)
        b.Padding = Thickness(8, 1, 8, 2)
        b.HorizontalAlignment = HorizontalAlignment.Right
        t = TextBlock()
        t.Text = r["status"]
        t.FontSize = 11
        t.Foreground = brush(fg)
        t.TextTrimming = TextTrimming.CharacterEllipsis
        b.Child = t
        holder = Border()
        holder.Width = 120
        holder.Margin = Thickness(8, 0, 0, 0)
        holder.Child = b
        holder.ToolTip = r["status"]
        return holder

    def _make_row(self, r, ticked):
        border = Border()
        border.Background = brush(SURFACE)
        border.CornerRadius = CornerRadius(6)
        border.Padding = Thickness(10, 6, 10, 6)
        border.Margin = Thickness(0, 0, 0, 4)
        dp = DockPanel()
        box = CheckBox()
        box.VerticalAlignment = VerticalAlignment.Center
        box.Margin = Thickness(0, 0, 8, 0)
        box.IsEnabled = r["tickable"]
        box.IsChecked = bool(ticked and r["tickable"])
        box.Click += RoutedEventHandler(self._on_tick)
        DockPanel.SetDock(box, Dock.Left)
        dp.Children.Add(box)
        if r["swatch"]:
            sw = Border()
            sw.Width = 22
            sw.Height = 4
            sw.CornerRadius = CornerRadius(2)
            sw.Background = brush(r["swatch"])
            sw.Margin = Thickness(0, 0, 8, 0)
            sw.VerticalAlignment = VerticalAlignment.Center
            DockPanel.SetDock(sw, Dock.Left)
            dp.Children.Add(sw)
        pill = self._pill(r)
        DockPanel.SetDock(pill, Dock.Right)
        dp.Children.Add(pill)
        for value, (_, width) in reversed(list(zip(r["cells"], self.tool.columns))):
            c = self._cell(value, width)
            DockPanel.SetDock(c, Dock.Right)
            dp.Children.Add(c)
        name = TextBlock()
        name.Text = r["name"]
        name.FontSize = 12
        name.Foreground = brush(TEXT)
        name.TextTrimming = TextTrimming.CharacterEllipsis
        name.VerticalAlignment = VerticalAlignment.Center
        name.ToolTip = r["name"]
        dp.Children.Add(name)
        border.Child = dp
        if not r["tickable"] and not self.tool.lists_all:
            border.Opacity = 0.5
        return border, box

    def _fill(self, first=False, keep=None):
        """(Re)build the rows from self.tool. keep: keys to check (after a purge: none)."""
        panel = self.ui["ListPanel"]
        panel.Children.Clear()
        self.rows = []
        for r in sorted(self.tool.rows, key=lambda r: not r["tickable"]):
            ticked = (self.tool.default_tick if keep is None else r["key"] in keep)
            border, box = self._make_row(r, ticked)
            panel.Children.Add(border)
            self.rows.append((r, border, box))
        unused = len(self.tool.unused_keys())
        if self.tool.lists_all:
            sub = u"{}  ·  {}".format(self.doc.Title, plural(len(self.tool.rows), self.tool.noun,
                                                                 self.tool.noun_plural))
        else:
            sub = u"{}  ·  {}  ·  {} unused".format(
                self.doc.Title, plural(len(self.tool.rows), self.tool.noun, self.tool.noun_plural), unused)
        self.ui["TbSub"].Text = sub
        self._apply_filter()

    def _apply_filter(self):
        text = (self.ui["SearchBox"].Text or u"").strip().lower()
        show_used = self.ui["ChkUsed"].IsChecked == True or self.tool.lists_all
        visible = 0
        for r, border, _ in self.rows:
            hay = u"{} {} {}".format(r["name"], u" ".join(r["cells"]), r["status"]).lower()
            show = (not text or text in hay) and (r["tickable"] or show_used)
            border.Visibility = Visibility.Visible if show else Visibility.Collapsed
            if show:
                visible += 1
        empty = self.ui["TbEmpty"]
        if visible:
            empty.Visibility = Visibility.Collapsed
        else:
            empty.Visibility = Visibility.Visible
            if text:
                empty.Text = u"Nothing matches the search."
            elif self.tool.lists_all:
                empty.Text = u"There are no {} in this model.".format(self.tool.noun_plural)
            else:
                empty.Text = u"No unused {} - nothing to purge.".format(self.tool.noun_plural)
        self._count()

    def _count(self):
        tickable = [b for r, _, b in self.rows if r["tickable"]]
        ticked = len([b for b in tickable if b.IsChecked == True])
        used = len(self.rows) - len(tickable)
        if self.tool.lists_all:
            text = u"{} of {} checked".format(ticked, len(tickable))
        else:
            text = u"{} of {} unused checked  ·  {} used {}".format(
                ticked, len(tickable), used, u"shown (can't be checked)" if self.ui["ChkUsed"].IsChecked == True
                else u"hidden")
        self.ui["TbCount"].Text = text
        self.ui["BtnPurge"].Content = u"Purge {}".format(ticked) if ticked else u"Purge"

    def _status(self, text, kind="info"):
        bg, fg = STATUS[kind]
        self.ui["BdStatus"].Background = brush(bg)
        self.ui["TbStatus"].Foreground = brush(fg)
        self.ui["TbStatus"].Text = text

    # ------------------------------------------------------------- events
    def _on_search(self, sender, args):
        self.ui["SearchHint"].Visibility = Visibility.Collapsed if self.ui["SearchBox"].Text else Visibility.Visible
        self._apply_filter()

    def _on_filter(self, sender, args):
        self._apply_filter()

    def _set_visible(self, state):
        for r, border, box in self.rows:
            if box.IsEnabled and border.Visibility == Visibility.Visible:
                box.IsChecked = state
        self._count()

    def _on_all(self, sender, args):
        self._set_visible(True)

    def _on_none(self, sender, args):
        self._set_visible(False)

    def _on_tick(self, sender, args):
        self._count()

    def _on_close(self, sender, args):
        self.w.Close()

    def _on_purge(self, sender, args):
        keys = [r["key"] for r, _, b in self.rows if b.IsEnabled and b.IsChecked == True]
        if not keys:
            self._status(u"Check at least one {} to purge.".format(self.tool.noun), "warn")
            return
        if self.tool.lists_all or not self.tool.default_tick:
            if not forms.alert(u"Delete {}? This is one Undo.".format(
                    plural(len(keys), self.tool.noun, self.tool.noun_plural)),
                    title=u"Purge {}".format(self.tool.title), yes=True, no=True):
                return
        try:
            message, kind = self._purge(keys)
        except Exception as ex:
            message, kind = u"The purge stopped and was undone: {}".format(ex), "warn"
        fresh = self.factory(self.doc, self.cache)
        if fresh is not None:
            self.tool = fresh
        self._fill(keep=set())
        self._status(message, kind)

    def _purge(self, keys):
        doc = self.doc
        tg = DB.TransactionGroup(doc, u"Purge {}".format(self.tool.title))
        tg.Start()
        try:
            result = self.tool.apply(keys)
            tg.Assimilate()
        except Exception:
            if tg.HasStarted() and not tg.HasEnded():
                tg.RollBack()
            raise
        parts = [u"Purged {}.".format(plural(len(result.deleted), self.tool.noun, self.tool.noun_plural))]
        if result.dependents:
            parts.append(u"Revit removed {} dependent elements with them.".format(result.dependents))
        kind = "ok"
        if result.kept:
            parts.append(u"Kept {} that turned out to be in use: {}.".format(
                len(result.kept), u", ".join(n for n, _ in result.kept[:8])))
            kind = "warn"
        if result.failed:
            parts.append(u"{} couldn't be deleted: {}.".format(
                len(result.failed), u"; ".join(u"{} ({})".format(n, m) for n, m in result.failed[:5])))
            kind = "warn"
        if not result.deleted:
            kind = "warn"
        parts.append(u"One Undo puts it all back.")
        return u" ".join(parts), kind

    def show(self):
        frame = DispatcherFrame()

        def on_closed(sender, args):
            frame.Continue = False

        self.w.Closed += EventHandler(on_closed)
        self.w.Show()
        Dispatcher.PushFrame(frame)


def run(uiapp, kind):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document if uidoc is not None else None
    if doc is None or doc.IsFamilyDocument:
        forms.alert(u"Open a project first.", title=u"Purge", exitscript=True)
        return
    factory = KINDS[kind]
    cache = {"active": eid_int(uidoc.ActiveView.Id) if uidoc.ActiveView is not None else None}
    tool = factory(doc, cache)
    if tool is None:
        return  # cancelled while reading
    PurgeWindow(uiapp, doc, kind, factory, tool, cache).show()
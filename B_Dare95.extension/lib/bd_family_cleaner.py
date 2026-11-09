# -*- coding: utf-8 -*-
"""bd_family_cleaner - engine for the Family Cleaner (Project Families) button.

Cleans one family document and the families nested inside it, down to
MAX_DEPTH levels, bottom-up:
  1. optional: delete CAD imports and PDFs placed inside the family
  2. purge Revit's own unused list (Document.GetUnusedElements), up to 3 passes
  3. open every nested family, clean it the same way, load it back (values kept)
  4. remove family parameters nothing uses

A family parameter counts as used when any of these is true:
  formula of another parameter | labels a dimension or an array |
  associated to an element parameter | reporting parameter |
  the parent family associates it (nested families) |
  shared parameter (kept unless the project option allows it after its check) |
  annotation family (labels can't be read through the API) |
  project data (text on placed copies)

Warnings are never suppressed. A Revit error rolls back only the transaction it
came from and is written to the report.

Put this file in B_Dare95.extension/lib/. The result window is bd_family_cleaner_report.py.
"""
import os
import re
import json
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
from System.Windows import (Thickness, CornerRadius, VerticalAlignment, TextTrimming, Visibility,
                            RoutedEventHandler, FontWeights)
from System.Windows.Controls import Border, DockPanel, Dock, CheckBox, TextBlock, StackPanel
from System.Windows.Input import Cursors, MouseButtonEventHandler
from System.Windows.Media import FontFamily
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper


MAX_DEPTH = 4      # nested levels below the family being cleaned (Revit's stack, see Revitaal notes)
PASSES = 3         # purge / parameter passes per document; stops early when nothing new goes

# Reloading these into the project resets settings the project keeps per type
# (MEP fitting loss methods) or rebuilds railings, so they are skipped.
NO_RELOAD = ("OST_DuctFitting", "OST_PipeFitting", "OST_CableTrayFitting", "OST_ConduitFitting",
             "OST_DuctAccessory", "OST_PipeAccessory", "OST_StairsRailingBaluster",
             "OST_RailingSupport", "OST_RailingTermination", "OST_ProfileFamilies")

MEMORY_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                           "B_Dare95", "family_cleaner_memory.json")

# IBM Carbon
BG, CARD, SURFACE, MUTED = "#161616", "#262626", "#393939", "#525252"
TEXT, SUBTEXT, ACCENT = "#F4F4F4", "#A8A8A8", "#F1C21B"


# =============================================================================
#  Small helpers
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
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_code))


def family_category_name(doc):
    try:
        cat = doc.OwnerFamily.FamilyCategory
        return cat.Name if cat is not None else u""
    except Exception:
        return u""


def is_annotation_family(doc):
    try:
        cat = doc.OwnerFamily.FamilyCategory
        return cat is not None and cat.CategoryType == DB.CategoryType.Annotation
    except Exception:
        return False


def no_reload_category_ids():
    ids = set()
    for name in NO_RELOAD:
        bic = getattr(DB.BuiltInCategory, name, None)
        if bic is not None:
            ids.add(int(bic))
    return ids


def editable_nested_ids(doc):
    """Ids (not elements: a reload can replace Family elements) of the nested loadable families."""
    owner = None
    if doc.IsFamilyDocument:
        try:
            owner = eid_int(doc.OwnerFamily.Id)
        except Exception:
            owner = None
    out = []
    for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        try:
            if f.IsEditable and not f.IsInPlace and eid_int(f.Id) != owner:
                out.append(f.Id)
        except Exception:
            pass
    return out


def junk_group_ids():
    """Identity Data, IFC and General parameter groups (ForgeTypeId)."""
    ids = set()
    for name in ("IdentityData", "Ifc", "General"):
        g = getattr(DB.GroupTypeId, name, None)
        if g is not None:
            ids.add(g.TypeId)
    return ids


# =============================================================================
#  Transactions (explicit Start / Commit, RollBack on failure only)
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


def start_transaction(doc, name, sink):
    t = DB.Transaction(doc, name)
    t.Start()
    options = t.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(_ErrorsRollBack(sink))
    options.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(options)
    return t


class KeepProjectValues(DB.IFamilyLoadOptions):
    """Load a cleaned family back without overwriting the values the target already has."""

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = False
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = False
        return True


# =============================================================================
#  Purge
# =============================================================================

_KINDS = {
    "Family": u"Nested families",
    "FamilySymbol": u"Nested types",
    "AnnotationSymbolType": u"Nested types",
    "Material": u"Materials",
    "AppearanceAssetElement": u"Appearance assets",
    "PropertySetElement": u"Material assets",
    "LinePatternElement": u"Line patterns",
    "FillPatternElement": u"Fill patterns",
    "TextNoteType": u"Text types",
    "DimensionType": u"Dimension types",
    "SpotDimensionType": u"Dimension types",
    "GroupType": u"Groups",
    "ImageType": u"Images",
    "CADLinkType": u"CAD types",
    "ImportInstance": u"CAD imports",
}


def kind_of(e):
    name = e.GetType().Name
    if name in _KINDS:
        return _KINDS[name]
    if isinstance(e, DB.FamilySymbol):
        return u"Nested types"
    if isinstance(e, DB.ElementType):
        return u"Other types"
    try:
        if e.Category is not None:
            return e.Category.Name
    except Exception:
        pass
    return name


def delete_items(doc, items, title, errors):
    """items: [(ElementId, kind)]. One transaction; batch first, one by one if the batch fails.
    Returns Counter of kinds deleted."""
    if not items:
        return Counter()
    done = []
    t = start_transaction(doc, title, errors)
    try:
        try:
            doc.Delete(List[DB.ElementId]([i for i, _ in items]))
            done = list(items)
        except Exception:
            done = []
            for i, kind in items:
                if doc.GetElement(i) is None:
                    continue
                try:
                    doc.Delete(i)
                    done.append((i, kind))
                except Exception:
                    pass
        status = t.Commit()
    except Exception as ex:
        if t.GetStatus() == DB.TransactionStatus.Started:
            t.RollBack()
        errors.append(u"{}: {}".format(title, ex))
        return Counter()
    if status != DB.TransactionStatus.Committed:
        return Counter()
    return Counter(kind for _, kind in done)


def purge_unused(doc, errors, passes=PASSES):
    """Revit's own Purge Unused list, repeated while it keeps freeing something."""
    total = Counter()
    for _ in range(passes):
        try:
            ids = list(doc.GetUnusedElements(HashSet[DB.ElementId]()))
        except Exception as ex:
            errors.append(u"Purge list: {}".format(ex))
            break
        items = []
        for i in ids:
            e = doc.GetElement(i)
            if e is not None:
                items.append((i, kind_of(e)))
        if not items:
            break
        got = delete_items(doc, items, u"Family Cleaner - purge unused", errors)
        if not got:
            break
        total.update(got)
    return total


def drop_cad_pdf(doc, errors):
    items = [(e.Id, u"CAD imports") for e in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance)]
    image_cls = getattr(DB, "ImageInstance", None)
    if image_cls is not None:
        for e in DB.FilteredElementCollector(doc).OfClass(image_cls):
            try:
                t = doc.GetElement(e.GetTypeId())
                path = (t.Path or u"") if t is not None else u""
            except Exception:
                path = u""
            if path.lower().endswith(u".pdf"):
                items.append((e.Id, u"PDFs"))
    return delete_items(doc, items, u"Family Cleaner - CAD and PDF", errors)


# =============================================================================
#  Family parameters
# =============================================================================

R_FORMULA = u"formula"
R_LABEL = u"label"
R_ASSOC = u"drives elements"
R_REPORTING = u"reporting"
R_PARENT = u"parent family"
R_SHARED = u"shared"
R_ANNOTATION = u"annotation family"
R_REFUSED = u"Revit refused"


def _labelled_ids(doc):
    """Family parameters that label a dimension or an array."""
    ids = set()
    for e in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
        label = None
        try:
            if isinstance(e, DB.Dimension):
                label = e.FamilyLabel
            elif isinstance(e, DB.BaseArray):
                label = e.Label
        except Exception:
            label = None
        if label is not None:
            ids.add(eid_int(label.Id))
    return ids


def _in_formula(name, formula, all_names=()):
    """True when the formula really references this parameter.
    Longer parameter names that contain this one ("Overall Width", "Rough Width" for "Width")
    are blanked out first: names can hold spaces, so a word-boundary check alone matched
    "Width" inside "Overall Width" and kept an unused Width parameter."""
    text = formula
    for other in sorted(all_names, key=len, reverse=True):
        if other != name and name in other:
            text = text.replace(other, u" ")
    pattern = u"(?<![\\w])" + re.escape(name) + u"(?![\\w])"
    return re.search(pattern, text, re.UNICODE) is not None


def _is_builtin(p):
    if eid_int(p.Id) < 0:
        return True
    try:
        return p.Definition.BuiltInParameter != DB.BuiltInParameter.INVALID
    except Exception:
        return False


def _group_id(p):
    try:
        return p.Definition.GetGroupTypeId().TypeId
    except Exception:
        return u""


class Rules(object):
    """What the parameter step must respect in one document.
    protect:     {name: reason} kept no matter what (parent associations, memory)
    guard:       callable(candidates) -> ({name: reason}, set(shared names allowed)); Project button only
    skip_params: True = parameters are not touched in this family and below"""

    def __init__(self, protect=None, guard=None, skip_params=False):
        self.protect = protect or {}
        self.guard = guard
        self.skip_params = skip_params


def analyse_parameters(doc, junk_only, rules, refused):
    """(candidates to remove [FamilyParameter], kept {name: reason}, out_of_scope count)."""
    fm = doc.FamilyManager
    params = list(fm.GetParameters())
    annotation = is_annotation_family(doc)
    labels = _labelled_ids(doc)
    formulas = []
    for p in params:
        try:
            if p.Formula:
                formulas.append((eid_int(p.Id), p.Formula))
        except Exception:
            pass
    groups = junk_group_ids() if junk_only else None
    names = set()
    for p in params:
        try:
            names.add(p.Definition.Name)
        except Exception:
            pass

    kept, first, out_of_scope = {}, [], 0
    for p in params:
        if _is_builtin(p):
            continue
        name = p.Definition.Name
        pid = eid_int(p.Id)
        reason = None
        if annotation:
            reason = R_ANNOTATION
        elif name in refused:
            reason = R_REFUSED
        elif getattr(p, "IsReporting", False):
            reason = R_REPORTING
        else:
            try:
                if p.AssociatedParameters.Size > 0:
                    reason = R_ASSOC
            except Exception:
                pass
        if reason is None and pid in labels:
            reason = R_LABEL
        if reason is None:
            for fid, text in formulas:
                if fid != pid and _in_formula(name, text, names):
                    reason = R_FORMULA
                    break
        if reason is None and name in rules.protect:
            reason = rules.protect[name]
        if reason is not None:
            kept[name] = reason
            continue
        if groups is not None and _group_id(p) not in groups:
            out_of_scope += 1
            continue
        first.append(p)

    protect, shared_ok = {}, set()
    if rules.guard is not None and first:
        protect, shared_ok = rules.guard(first)

    candidates = []
    for p in first:
        name = p.Definition.Name
        if name in protect:
            kept[name] = protect[name]
        elif p.IsShared and name not in shared_ok:
            kept[name] = R_SHARED
        else:
            candidates.append(p)
    return candidates, kept, out_of_scope


def remove_unused_parameters(doc, junk_only, rules, errors):
    """Repeats until nothing new goes (removing B can free A when only B's formula used A).
    Returns (removed names, kept {name: reason})."""
    removed, refused, kept = [], {}, {}
    for _ in range(PASSES):
        candidates, kept, _ = analyse_parameters(doc, junk_only, rules, refused)
        if not candidates:
            break
        done = []
        t = start_transaction(doc, u"Family Cleaner - remove unused parameters", errors)
        try:
            fm = doc.FamilyManager
            for p in candidates:
                name = p.Definition.Name
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    fm.RemoveParameter(p)
                    st.Commit()
                    done.append(name)
                except Exception as ex:
                    if st.GetStatus() == DB.TransactionStatus.Started:
                        st.RollBack()
                    refused[name] = u"{}".format(ex)
            status = t.Commit()
        except Exception as ex:
            if t.GetStatus() == DB.TransactionStatus.Started:
                t.RollBack()
            errors.append(u"Removing parameters: {}".format(ex))
            break
        if status != DB.TransactionStatus.Committed:
            errors.append(u"Removing parameters was rolled back by Revit")
            break
        removed.extend(done)
        if not done:
            break
    for name in refused:
        kept[name] = R_REFUSED
    return removed, kept


def parent_associations(parent_doc, nested_family_id):
    """Names of the nested family's parameters that the parent associates to one of its own
    parameters. Inside the nested document these look unused, so they must be protected."""
    names = set()
    fm = parent_doc.FamilyManager
    target = eid_int(nested_family_id)
    for inst in DB.FilteredElementCollector(parent_doc).OfClass(DB.FamilyInstance):
        try:
            sym = inst.Symbol
            if sym is None or eid_int(sym.Family.Id) != target:
                continue
        except Exception:
            continue
        for p in inst.Parameters:
            try:
                if fm.GetAssociatedFamilyParameter(p) is not None:
                    names.add(p.Definition.Name)
            except Exception:
                pass
    return names


# =============================================================================
#  Report rows
# =============================================================================

class Node(object):
    """One row of the report: one family (root or nested) and what happened to it."""

    def __init__(self, name, depth, category=u"", parent=None):
        self.name = name
        self.depth = depth
        self.category = category
        self.parent = parent
        self.status = u""
        self.purged = Counter()
        self.removed = []
        self.kept = {}
        self.nested_before = 0
        self.nested_after = 0
        self.errors = []

    @property
    def path(self):
        if self.parent is None:
            return self.name
        return self.parent.path + u" > " + self.name

    def own_changes(self):
        return bool(sum(self.purged.values()) or self.removed)


# =============================================================================
#  The cleaner
# =============================================================================

class CleanOptions(object):
    def __init__(self, depth=MAX_DEPTH, purge=True, params=True, junk_only=False, cad_pdf=False,
                 preview=False):
        self.depth = max(1, min(MAX_DEPTH, int(depth)))
        self.purge = purge
        self.params = params
        self.junk_only = junk_only
        self.cad_pdf = cad_pdf
        self.preview = preview


class FamilyCleaner(object):
    """clean(doc, name, rules) cleans an OPEN family document and its nested families.
    The caller owns the root document (keeps, saves, reloads or rolls it back).
    rows:        shared report list (Node)
    is_cancelled: callable, checked before every family is opened"""

    def __init__(self, options, rows=None, is_cancelled=None):
        self.opts = options
        self.rows = rows if rows is not None else []
        self.is_cancelled = is_cancelled
        self.cancelled = False
        self._open = []

    def _check_cancel(self):
        if self.cancelled:
            return True
        try:
            if self.is_cancelled is not None and self.is_cancelled():
                self.cancelled = True
        except Exception:
            pass
        return self.cancelled

    def clean(self, doc, name, rules=None):
        """Returns (root Node, changed)."""
        return self._clean(doc, name, 0, rules or Rules(), None)

    def _clean(self, doc, name, depth, rules, parent_node):
        node = Node(name, depth, family_category_name(doc), parent_node)
        self.rows.append(node)
        self._open.append(name)
        nested_changed = False
        try:
            nested = editable_nested_ids(doc)
            node.nested_before = len(nested)

            if self.opts.cad_pdf:
                node.purged.update(drop_cad_pdf(doc, node.errors))
            if self.opts.purge:
                node.purged.update(purge_unused(doc, node.errors))

            nested = editable_nested_ids(doc)  # what the purge left: the used ones
            if depth < self.opts.depth:
                for fid in nested:
                    if self._check_cancel():
                        break
                    if self._child(doc, fid, depth, rules, node):
                        nested_changed = True
                if nested_changed and self.opts.purge:
                    node.purged.update(purge_unused(doc, node.errors))
            else:
                for fid in nested:
                    fam = doc.GetElement(fid)
                    if fam is not None:
                        skipped = Node(elem_name(fam), depth + 1, u"", node)
                        skipped.status = u"Not opened: deeper than {} levels".format(self.opts.depth)
                        self.rows.append(skipped)

            if self.opts.params and not rules.skip_params:
                node.removed, node.kept = remove_unused_parameters(doc, self.opts.junk_only, rules,
                                                                   node.errors)
            node.nested_after = len(editable_nested_ids(doc))
            changed = node.own_changes() or nested_changed
            if self.opts.preview:
                node.status = u"Would clean" if changed else u"Nothing to clean"
            else:
                node.status = u"Cleaned" if changed else u"Unchanged"
            if self.cancelled and depth == 0:
                node.status += u" (stopped early)"
            return node, changed
        except Exception as ex:
            node.status = u"Failed: {}".format(ex)
            return node, False
        finally:
            self._open.pop()

    def _child(self, parent_doc, fid, depth, rules, parent_node):
        """Clean one nested family and load it back into its parent. True when the parent changed."""
        fam = parent_doc.GetElement(fid)
        if fam is None:
            return False  # replaced by an earlier reload (shared nested family): already cleaned
        name = elem_name(fam)
        if name in self._open:
            node = Node(name, depth + 1, u"", parent_node)
            node.status = u"Not opened: the same family is open higher up"
            self.rows.append(node)
            return False
        protect = dict((n, R_PARENT) for n in parent_associations(parent_doc, fid))
        try:
            child = parent_doc.EditFamily(fam)
        except Exception as ex:
            node = Node(name, depth + 1, u"", parent_node)
            node.status = u"Failed to open: {}".format(ex)
            self.rows.append(node)
            return False
        try:
            node, changed = self._clean(child, name, depth + 1,
                                        Rules(protect=protect, skip_params=rules.skip_params),
                                        parent_node)
            if not changed or self.opts.preview:
                return False
            try:
                child.LoadFamily(parent_doc, KeepProjectValues())
                return True
            except Exception as ex:
                node.status = u"Cleaned, but loading it back failed: {}".format(ex)
                return False
        finally:
            try:
                if child.IsValidObject:
                    child.Close(False)
            except Exception:
                pass


# =============================================================================
#  Project button: checks against the project
# =============================================================================

def placed_instance_ids(doc, fam):
    ids = []
    for sid in fam.GetFamilySymbolIds():
        ids.extend(DB.FilteredElementCollector(doc)
                   .WherePasses(DB.FamilyInstanceFilter(doc, sid)).ToElementIds())
    return ids


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


class ProjectContext(object):
    """Project-wide facts read once per run."""

    def __init__(self, doc, allow_shared):
        self.doc = doc
        self.allow_shared = allow_shared
        self.schedule_ids = set()
        self.filter_ids = set()
        self.bound_ids = set()
        if not allow_shared:
            return
        for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
            try:
                d = vs.Definition
                for i in range(d.GetFieldCount()):
                    self.schedule_ids.add(eid_int(d.GetField(i).ParameterId))
            except Exception:
                pass
        for pf in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement):
            try:
                ef = pf.GetElementFilter()
                if ef is not None:
                    self.filter_ids.update(_rule_param_ids(ef))
            except Exception:
                pass
        it = doc.ParameterBindings.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            try:
                self.bound_ids.add(eid_int(it.Key.Id))
            except Exception:
                pass


def _has_text(p):
    try:
        return p is not None and p.HasValue and bool(p.AsString())
    except Exception:
        return False


def make_project_guard(ctx, fam):
    """Guard for a top-level family's parameters (see Rules.guard).
    - instance text parameters with text on any placed copy: kept (project data)
    - shared parameters: only when allowed AND no schedule, filter, project binding or
      placed copy value uses them. Tags can't be checked through the API."""
    instances = [ctx.doc.GetElement(i) for i in placed_instance_ids(ctx.doc, fam)]
    instances = [i for i in instances if i is not None]

    def guard(candidates):
        protect, shared_ok = {}, set()
        for p in candidates:
            name = p.Definition.Name
            if p.IsShared:
                if not ctx.allow_shared:
                    continue  # kept as "shared" by the caller
                reason = None
                try:
                    guid = p.GUID
                    spe = DB.SharedParameterElement.Lookup(ctx.doc, guid)
                except Exception:
                    guid, spe = None, None
                if spe is not None:
                    sid = eid_int(spe.Id)
                    if sid in ctx.schedule_ids:
                        reason = u"in a schedule"
                    elif sid in ctx.filter_ids:
                        reason = u"in a view filter"
                    elif sid in ctx.bound_ids:
                        reason = u"project parameter"
                if reason is None and guid is not None and p.IsInstance:
                    for inst in instances:
                        try:
                            q = inst.get_Parameter(guid)
                        except Exception:
                            q = None
                        if q is None or not q.HasValue:
                            continue
                        if q.StorageType != DB.StorageType.String or q.AsString():
                            reason = u"values on placed copies"
                            break
                if reason is None:
                    shared_ok.add(name)
                else:
                    protect[name] = reason
            elif p.IsInstance and p.StorageType == DB.StorageType.String:
                for inst in instances:
                    if _has_text(inst.LookupParameter(name)):
                        protect[name] = u"text on placed copies"
                        break
        return protect, shared_ok

    return guard


def _param_value(doc, p):
    try:
        if not p.HasValue:
            return None
        st = p.StorageType
        if st == DB.StorageType.String:
            return p.AsString()
        if st == DB.StorageType.Double:
            return round(p.AsDouble(), 6)
        if st == DB.StorageType.Integer:
            return p.AsInteger()
        if st == DB.StorageType.ElementId:
            e = doc.GetElement(p.AsElementId())
            return elem_name(e) if e is not None else eid_int(p.AsElementId())
    except Exception:
        return None
    return None


def snapshot(doc, fam):
    """Placed copies (count and boxes) and every type's parameter values, before a reload."""
    ids = placed_instance_ids(doc, fam)
    boxes = {}
    for i in ids:
        e = doc.GetElement(i)
        b = e.get_BoundingBox(None) if e is not None else None
        boxes[eid_int(i)] = (b.Min.X, b.Min.Y, b.Min.Z, b.Max.X, b.Max.Y, b.Max.Z) if b is not None else None
    types = {}
    for sid in fam.GetFamilySymbolIds():
        s = doc.GetElement(sid)
        if s is None:
            continue
        values = {}
        for p in s.Parameters:
            try:
                values[p.Definition.Name] = _param_value(doc, p)
            except Exception:
                pass
        types[elem_name(s)] = values
    return {"count": len(ids), "boxes": boxes, "types": types}


def find_family(doc, fam_id, name):
    """The project's Family element now: by id, else by name. A reload can replace the
    Family element with a new id (Revit hands back the new one from LoadFamily)."""
    fam = doc.GetElement(fam_id) if fam_id is not None else None
    if isinstance(fam, DB.Family):
        return fam
    for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        if elem_name(f) == name:
            return f
    return None


def _boxes_differ(a, b, tol):
    if (a is None) != (b is None):
        return True
    return a is not None and any(abs(x - y) > tol for x, y in zip(a, b))


def compare_snapshots(before, after, removed_names, tol=1e-4):
    """None when nothing changed, else the first difference in plain words."""
    if before["count"] != after["count"]:
        return u"placed copies went from {} to {}".format(before["count"], after["count"])
    if set(before["boxes"]) == set(after["boxes"]):
        for key, b in before["boxes"].items():
            if _boxes_differ(after["boxes"][key], b, tol):
                return u"placed copy {} moved or changed size".format(key)
    else:
        # the placed copies got new ids with the reload: compare where they are, not who they are
        def ordered(boxes):
            return sorted(tuple(round(v, 4) for v in b) for b in boxes.values() if b is not None)
        now, then = ordered(after["boxes"]), ordered(before["boxes"])
        if len(now) != len(then):
            return u"a placed copy changed its geometry"
        for a, b in zip(now, then):
            if _boxes_differ(a, b, tol):
                return u"a placed copy moved or changed size"
    for tname, values in before["types"].items():
        now = after["types"].get(tname)
        if now is None:
            return u"type '{}' is gone".format(tname)
        for pname, v in values.items():
            if pname in removed_names or pname not in now:
                continue
            w = now[pname]
            if isinstance(v, float) and isinstance(w, float):
                if abs(v - w) > tol:
                    return u"type '{}': {} changed".format(tname, pname)
            elif v != w:
                return u"type '{}': {} changed".format(tname, pname)
    return None


def load_memory():
    try:
        with open(MEMORY_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_memory(memory):
    try:
        folder = os.path.dirname(MEMORY_PATH)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(MEMORY_PATH, "w") as f:
            json.dump(memory, f, indent=2, sort_keys=True)
    except Exception:
        pass


# =============================================================================
#  UI (IBM Carbon, XamlReader.Parse, PushFrame)
# =============================================================================

RESOURCES = u"""
<Style x:Key="Card" TargetType="Border">
    <Setter Property="Background" Value="#262626"/>
    <Setter Property="CornerRadius" Value="8"/>
    <Setter Property="Padding" Value="14,12"/>
    <Setter Property="Margin" Value="0,0,0,8"/>
</Style>
<Style x:Key="H1" TargetType="TextBlock">
    <Setter Property="Foreground" Value="#F4F4F4"/>
    <Setter Property="FontSize" Value="16"/>
    <Setter Property="FontWeight" Value="Bold"/>
</Style>
<Style x:Key="Label" TargetType="TextBlock">
    <Setter Property="Foreground" Value="#F4F4F4"/>
    <Setter Property="FontSize" Value="13"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
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
<Style x:Key="Pill" TargetType="ToggleButton">
    <Setter Property="Foreground" Value="#F4F4F4"/>
    <Setter Property="Background" Value="#393939"/>
    <Setter Property="Height" Value="30"/>
    <Setter Property="MinWidth" Value="40"/>
    <Setter Property="Margin" Value="0,0,6,0"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="Template">
        <Setter.Value>
            <ControlTemplate TargetType="ToggleButton">
                <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="6" Padding="12,4">
                    <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Border>
                <ControlTemplate.Triggers>
                    <Trigger Property="IsChecked" Value="True">
                        <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                        <Setter Property="Foreground" Value="#161616"/>
                    </Trigger>
                    <Trigger Property="IsEnabled" Value="False">
                        <Setter TargetName="Bd" Property="Opacity" Value="0.4"/>
                    </Trigger>
                </ControlTemplate.Triggers>
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
    <Setter Property="MinWidth" Value="88"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="Template">
        <Setter.Value>
            <ControlTemplate TargetType="Button">
                <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="6" Padding="14,6">
                    <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Border>
                <ControlTemplate.Triggers>
                    <Trigger Property="IsEnabled" Value="False">
                        <Setter TargetName="Bd" Property="Opacity" Value="0.4"/>
                    </Trigger>
                </ControlTemplate.Triggers>
            </ControlTemplate>
        </Setter.Value>
    </Setter>
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
"""

WINDOW_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="%%TITLE%%" Width="%%WIDTH%%" SizeToContent="Height" MaxHeight="920"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="#161616" FontFamily="Segoe UI">
    <Window.Resources>%%RES%%</Window.Resources>
    <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel Margin="20">%%BODY%%</StackPanel>
    </ScrollViewer>
</Window>
"""

OPTIONS_XAML = u"""
<Border Style="{StaticResource Card}">
    <StackPanel>
        <TextBlock Text="Nested levels to clean" Style="{StaticResource Label}"/>
        <StackPanel Orientation="Horizontal" Margin="0,8,0,4">
            <ToggleButton x:Name="Depth1" Content="1" Style="{StaticResource Pill}"/>
            <ToggleButton x:Name="Depth2" Content="2" Style="{StaticResource Pill}"/>
            <ToggleButton x:Name="Depth3" Content="3" Style="{StaticResource Pill}"/>
            <ToggleButton x:Name="Depth4" Content="4" IsChecked="True" Style="{StaticResource Pill}"/>
        </StackPanel>
        <TextBlock Style="{StaticResource Hint}"
                   Text="Level 1 is the families nested in the family being cleaned. Unused nested families are deleted at any level; this sets how deep the used ones get cleaned themselves. Deeper takes longer."/>
    </StackPanel>
</Border>
<Border Style="{StaticResource Card}">
    <StackPanel>
        <TextBlock Text="What to clean" Style="{StaticResource Label}"/>
        <CheckBox x:Name="ChkPurge" IsChecked="True" Margin="0,8,0,0"
                  Content="Purge unused content (nested families, types, materials, patterns, styles)"/>
        <CheckBox x:Name="ChkParams" IsChecked="True" Margin="0,8,0,0"
                  Content="Remove family parameters nothing uses"/>
        <StackPanel Orientation="Horizontal" Margin="24,6,0,0">
            <ToggleButton x:Name="ScopeAll" Content="All groups" IsChecked="True" Style="{StaticResource Pill}"/>
            <ToggleButton x:Name="ScopeJunk" Content="Identity Data, IFC, General only" Style="{StaticResource Pill}"/>
        </StackPanel>
        <TextBlock Style="{StaticResource Hint}" Margin="24,4,0,0"
                   Text="Kept when used by a formula, a dimension or array label, an element, a reporting relation or the parent family. Tag/annotation families keep all theirs; shared ones follow the project option."/>
        <CheckBox x:Name="ChkCad" Margin="0,10,0,0"
                  Content="Delete CAD imports and PDFs inside the families"/>
        <TextBlock Style="{StaticResource Hint}" Margin="24,2,0,0"
                   Text="Off by default: a CAD drawing inside a family is often its symbol."/>
    </StackPanel>
</Border>
"""

BUTTONS_XAML = u"""
<StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
    <Button x:Name="BtnCancel" Content="Cancel" Style="{StaticResource Secondary}" Height="34" MinWidth="88" Margin="0,0,10,0"/>
    <Button x:Name="BtnRun" Content="Clean" Style="{StaticResource Primary}"/>
</StackPanel>
"""


def build_window(title, width, body, owner_handle=None):
    xaml = (WINDOW_XAML.replace(u"%%TITLE%%", title)
            .replace(u"%%WIDTH%%", u"{}".format(width))
            .replace(u"%%RES%%", RESOURCES)
            .replace(u"%%BODY%%", body))
    window = XamlReader.Parse(xaml)
    if owner_handle is not None:
        try:
            WindowInteropHelper(window).Owner = owner_handle
        except Exception:
            pass
    return window


def show_blocking(window):
    """Show() plus a pushed dispatcher frame until the window closes (instead of ShowDialog)."""
    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)


def _radio(window, names):
    buttons = [window.FindName(n) for n in names]

    def make(name):
        def on_click(sender, args):
            for b in buttons:
                b.IsChecked = (b.Name == name)
        return on_click

    for b in buttons:
        b.Click += RoutedEventHandler(make(b.Name))
    return buttons


def wire_options(window):
    _radio(window, ["Depth1", "Depth2", "Depth3", "Depth4"])
    scope = _radio(window, ["ScopeAll", "ScopeJunk"])
    chk_params = window.FindName("ChkParams")

    def on_params(sender, args):
        for b in scope:
            b.IsEnabled = bool(chk_params.IsChecked)

    chk_params.Click += RoutedEventHandler(on_params)


def save_controls(window, names):
    """{name: IsChecked or Text} for the named controls, to rebuild a window as it was."""
    saved = {}
    for name in names:
        control = window.FindName(name)
        if control is None:
            continue
        if hasattr(control, "IsChecked"):
            saved[name] = control.IsChecked
        elif hasattr(control, "Text"):
            saved[name] = control.Text
    return saved


def restore_controls(window, saved):
    for name, value in (saved or {}).items():
        control = window.FindName(name)
        if control is None:
            continue
        if hasattr(control, "IsChecked"):
            control.IsChecked = value
        elif hasattr(control, "Text"):
            control.Text = value
    chk_params = window.FindName("ChkParams")
    if chk_params is not None:
        for name in ("ScopeAll", "ScopeJunk"):
            window.FindName(name).IsEnabled = bool(chk_params.IsChecked)


# Inspection Mode runs as if every setting were checked
INSPECTION_SETTINGS = {"Depth1": False, "Depth2": False, "Depth3": False, "Depth4": True,
                       "ChkPurge": True, "ChkParams": True, "ScopeAll": True, "ScopeJunk": False,
                       "ChkCad": True, "ChkShared": True}


def read_options(window):
    if window.FindName("ChkInspect").IsChecked:
        return CleanOptions(depth=MAX_DEPTH, purge=True, params=True, junk_only=False, cad_pdf=True,
                            preview=True)
    depth = MAX_DEPTH
    for n in range(1, MAX_DEPTH + 1):
        if window.FindName("Depth{}".format(n)).IsChecked:
            depth = n
    return CleanOptions(
        depth=depth,
        purge=bool(window.FindName("ChkPurge").IsChecked),
        params=bool(window.FindName("ChkParams").IsChecked),
        junk_only=bool(window.FindName("ScopeJunk").IsChecked),
        cad_pdf=bool(window.FindName("ChkCad").IsChecked),
        preview=False)


class GroupedCheckList(object):
    """The checklist grouped into dropdowns (categories). Needs ListPanel, SearchBox, SearchHint,
    CountText, BtnAll and BtnNone in the window.
    items: dicts {key, title, info, group, checked, enabled, reason}
    A dropdown's own checkbox checks or clears its families (only the ones the search shows);
    it shows a partial state when some are checked. Searching opens the dropdowns with matches."""

    def __init__(self, window, noun=u"families", group_noun=u"categories"):
        self.noun = noun
        self.group_noun = group_noun
        self.panel = window.FindName("ListPanel")
        self.search = window.FindName("SearchBox")
        self.hint = window.FindName("SearchHint")
        self.count = window.FindName("CountText")
        self.groups = []
        self.search.TextChanged += self._on_search
        window.FindName("BtnAll").Click += RoutedEventHandler(self._on_all)
        window.FindName("BtnNone").Click += RoutedEventHandler(self._on_none)

    # ---- build
    def set_items(self, items):
        self.panel.Children.Clear()
        self.groups = []
        order = []
        by_group = {}
        for item in items:
            name = item.get("group") or u"Other"
            if name not in by_group:
                by_group[name] = []
                order.append(name)
            by_group[name].append(item)
        for name in sorted(order, key=lambda n: n.lower()):
            group = self._make_group(name, by_group[name])
            self.groups.append(group)
            self.panel.Children.Add(group["header"])
            self.panel.Children.Add(group["body"])
        self._apply_filter()

    def _make_group(self, name, items):
        group = {"name": name, "open": False, "rows": []}

        header = Border()
        header.BorderBrush = brush(MUTED)
        header.BorderThickness = Thickness(0, 0, 0, 1)
        header.Padding = Thickness(4, 6, 6, 6)
        header.Margin = Thickness(0, 2, 0, 2)
        header.Background = brush(CARD)
        header.Cursor = Cursors.Hand
        dock = DockPanel()
        chevron = TextBlock()
        chevron.Text = u"\u25B8"
        chevron.FontFamily = FontFamily(u"Segoe UI Symbol")
        chevron.Foreground = brush(ACCENT)
        chevron.Width = 18
        chevron.VerticalAlignment = VerticalAlignment.Center
        DockPanel.SetDock(chevron, Dock.Left)
        tick = CheckBox()
        tick.VerticalAlignment = VerticalAlignment.Center
        tick.Margin = Thickness(0, 0, 8, 0)
        tick.ToolTip = u"Check or clear every family in this category"
        DockPanel.SetDock(tick, Dock.Left)
        count = TextBlock()
        count.Foreground = brush(SUBTEXT)
        count.FontSize = 11
        count.VerticalAlignment = VerticalAlignment.Center
        DockPanel.SetDock(count, Dock.Right)
        title = TextBlock()
        title.Text = name
        title.Foreground = brush(TEXT)
        title.FontSize = 12
        title.FontWeight = FontWeights.SemiBold
        title.TextTrimming = TextTrimming.CharacterEllipsis
        title.VerticalAlignment = VerticalAlignment.Center
        dock.Children.Add(chevron)
        dock.Children.Add(tick)
        dock.Children.Add(count)
        dock.Children.Add(title)
        header.Child = dock

        body = StackPanel()
        body.Margin = Thickness(26, 2, 0, 6)
        body.Visibility = Visibility.Collapsed
        for item in items:
            border, box = _check_row(item)
            box.Click += RoutedEventHandler(self._make_row_tick(group))
            body.Children.Add(border)
            group["rows"].append((item, border, box))

        group.update({"header": header, "body": body, "chevron": chevron, "tick": tick, "count": count})
        header.MouseLeftButtonUp += MouseButtonEventHandler(self._make_toggle(group))
        tick.Click += RoutedEventHandler(self._make_group_tick(group))
        return group

    # ---- events
    def _make_toggle(self, group):
        def handler(sender, args):
            group["open"] = not group["open"]
            self._apply_filter()
        return handler

    def _make_group_tick(self, group):
        def handler(sender, args):
            state = group["tick"].IsChecked == True
            for item, border, box in group["rows"]:
                if box.IsEnabled and border.Visibility == Visibility.Visible:
                    box.IsChecked = state
            self._refresh_counts()
        return handler

    def _make_row_tick(self, group):
        def handler(sender, args):
            self._refresh_counts()
        return handler

    def _on_search(self, sender, args):
        self.hint.Visibility = Visibility.Collapsed if self.search.Text else Visibility.Visible
        self._apply_filter()

    def _set_visible(self, state):
        for group in self.groups:
            for item, border, box in group["rows"]:
                if box.IsEnabled and border.Visibility == Visibility.Visible:
                    box.IsChecked = state
        self._refresh_counts()

    def _on_all(self, sender, args):
        self._set_visible(True)

    def _on_none(self, sender, args):
        self._set_visible(False)

    # ---- state
    def _apply_filter(self):
        text = (self.search.Text or u"").strip().lower()
        for group in self.groups:
            hits = 0
            for item, border, _ in group["rows"]:
                hay = u"{} {} {}".format(item.get("title") or u"", item.get("info") or u"",
                                          group["name"]).lower()
                show = not text or text in hay
                border.Visibility = Visibility.Visible if show else Visibility.Collapsed
                if show:
                    hits += 1
            group["header"].Visibility = Visibility.Visible if hits else Visibility.Collapsed
            is_open = hits > 0 and (group["open"] or bool(text))
            group["body"].Visibility = Visibility.Visible if is_open else Visibility.Collapsed
            group["chevron"].Text = u"\u25BE" if is_open else u"\u25B8"
        self._refresh_counts()

    def _refresh_counts(self):
        total = ticked = 0
        for group in self.groups:
            enabled = [b for _, _, b in group["rows"] if b.IsEnabled]
            on = len([b for b in enabled if b.IsChecked == True])
            skipped = len(group["rows"]) - len(enabled)
            total += len(group["rows"])
            ticked += on
            group["tick"].IsEnabled = bool(enabled)
            if enabled and on == len(enabled):
                group["tick"].IsChecked = True
            elif on == 0:
                group["tick"].IsChecked = False
            else:
                group["tick"].IsChecked = None
            text = u"{} of {} checked".format(on, len(enabled))
            if skipped:
                text += u"  \u00b7  {} skipped".format(skipped)
            group["count"].Text = text
        self.count.Text = u"{} of {} {} checked  \u00b7  {} {}".format(
            ticked, total, self.noun, len(self.groups), self.group_noun)

    def set_checked(self, keys, only=False):
        """Check these keys (only=True clears every other one) and open their dropdowns."""
        keys = set(keys)
        for group in self.groups:
            for item, _, box in group["rows"]:
                if not box.IsEnabled:
                    continue
                if item["key"] in keys:
                    box.IsChecked = True
                    group["open"] = True
                elif only:
                    box.IsChecked = False
        self._apply_filter()

    def open_groups(self):
        return set(g["name"] for g in self.groups if g["open"])

    def restore_open(self, names):
        for group in self.groups:
            group["open"] = group["name"] in names
        self._apply_filter()

    def selected_keys(self):
        keys = []
        for group in self.groups:
            for item, _, box in group["rows"]:
                if box.IsEnabled and box.IsChecked == True:
                    keys.append(item["key"])
        return keys


def _check_row(item):
    """One family checkbox row."""
    enabled = item.get("enabled", True)
    border = Border()
    border.Background = brush(SURFACE)
    border.CornerRadius = CornerRadius(6)
    border.Padding = Thickness(10, 6, 10, 6)
    border.Margin = Thickness(0, 0, 0, 4)
    dock = DockPanel()
    box = CheckBox()
    box.IsChecked = bool(item.get("checked")) and enabled
    box.IsEnabled = enabled
    box.VerticalAlignment = VerticalAlignment.Center
    box.Margin = Thickness(0, 0, 8, 0)
    DockPanel.SetDock(box, Dock.Left)
    info = TextBlock()
    info.Text = item.get("info") or u""
    info.Foreground = brush(SUBTEXT)
    info.FontSize = 11
    info.VerticalAlignment = VerticalAlignment.Center
    info.Margin = Thickness(8, 0, 0, 0)
    DockPanel.SetDock(info, Dock.Right)
    title = TextBlock()
    title.Text = item.get("title") or u""
    title.Foreground = brush(TEXT)
    title.FontSize = 12
    title.TextTrimming = TextTrimming.CharacterEllipsis
    title.VerticalAlignment = VerticalAlignment.Center
    dock.Children.Add(box)
    dock.Children.Add(info)
    dock.Children.Add(title)
    border.Child = dock
    if not enabled:
        border.Opacity = 0.55
        if item.get("reason"):
            border.ToolTip = item["reason"]
            info.Text = item["reason"]
    return border, box
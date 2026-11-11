# -*- coding: utf-8 -*-
"""Model Health Check: the checks, shared by the full Model Health Check button
(HTML report) and the section reports under QoL > Quick Reports.

Every check reads the module-level ``doc``. Call ``run_sections(document, ...)``
for each run: it sets ``doc`` and clears the caches. That matters because the
Quick Reports buttons use a persistent engine, where this module stays loaded
between runs and between models.
"""

import math
import os
import re


from Autodesk.Revit.DB import (
    AreaScheme,
    AreaVolumeSettings,
    AssemblyInstance,
    AttachmentType,
    BasePoint,
    BrowserOrganization,
    BuiltInCategory,
    BuiltInParameter,
    CategoryType,
    CeilingType,
    CurtainSystemType,
    CurveElement,
    DesignOption,
    DetailCurve,
    DimensionType,
    Element,
    ElementDesignOptionFilter,
    ElementId,
    ElementType,
    ElementWorksetFilter,
    Family,
    FamilyInstance,
    FilledRegionType,
    FillPatternElement,
    FilteredElementCollector,
    FilteredWorksetCollector,
    FloorType,
    Grid,
    GraphicsStyleType,
    GridType,
    Group,
    ImageType,
    ImportInstance,
    Level,
    LevelType,
    LinePatternElement,
    LocationPoint,
    ModelCurve,
    MullionType,
    ReferencePlane,
    RevitLinkInstance,
    RevitLinkType,
    RoofType,
    ScheduleSheetInstance,
    StorageType,
    TextNoteType,
    View,
    View3D,
    ViewSchedule,
    ViewSheet,
    ViewType,
    WallType,
    WorksetKind,
    XYZ,
)
from Autodesk.Revit.DB.Mechanical import (
    DuctType, FlexDuctType, MechanicalSystem, MechanicalSystemType,
)
from Autodesk.Revit.DB.Plumbing import (
    FlexPipeType, PipeType, PipingSystem, PipingSystemType,
)
import bd_core as bd

try:
    basestring_type = basestring
except NameError:       # only for testing outside IronPython
    basestring_type = str

doc = None

FT_MM = bd.MM_PER_FT

PASS, FAIL, COUNT, LIST, RESULT = "PASS", "FAIL", "COUNT", "COUNT AND LIST", "RESULT"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
eid_value = bd.eid_int


def ename(element):
    if element is None:
        return u""
    try:
        return Element.Name.GetValue(element) or u""
    except Exception:
        pass
    try:
        return element.Name or u""
    except Exception:
        return u""


def cat_name(element):
    try:
        return element.Category.Name if element.Category is not None else u""
    except Exception:
        return u""


def bip(element, name):
    """A built-in parameter of any element, ElementTypes included."""
    b = getattr(BuiltInParameter, name, None)
    if b is None or element is None:
        return None
    try:
        return Element.get_Parameter(element, b)
    except Exception:
        try:
            return element.get_Parameter(b)
        except Exception:
            return None


def param_text(p):
    if p is None or not p.HasValue:
        return u""
    try:
        if p.StorageType == StorageType.String:
            return p.AsString() or u""
        return p.AsValueString() or u""
    except Exception:
        return u""


def number(n):
    """1234567 -> '1,234,567'."""
    text = u"{0}".format(int(n))
    sign = u"-" if text.startswith(u"-") else u""
    digits = text.lstrip(u"-")
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return sign + u",".join(groups)


def instances(category):
    return list(FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType())


def type_rows(cls=None, category=None):
    """[(Category, Type, 'Category : Type : Name')] of element types."""
    col = FilteredElementCollector(doc)
    col = col.OfClass(cls) if cls is not None else col.OfCategory(category).WhereElementIsElementType()
    rows = []
    for t in col:
        c, n = cat_name(t), ename(t)
        rows.append((c, n, u"{0} : Type : {1}".format(c, n)))
    return sorted(rows, key=lambda r: (r[0].lower(), r[1].lower()))


_CACHE = {}


def instances_by_type():
    """{type id: [ids of the placed elements of that type]}, read once per run.
    Lets a type list (wall types, text styles, ...) select the elements using each type."""
    found = _CACHE.get("by_type")
    if found is None:
        found = {}
        for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
            if isinstance(e, View):
                continue
            try:
                t = e.GetTypeId()
            except Exception:
                continue
            if t is None or t == ElementId.InvalidElementId:
                continue
            found.setdefault(eid_value(t), []).append(eid_value(e.Id))
        _CACHE["by_type"] = found
    return found


def instances_by_family():
    """{family id: [ids of its placed instances]}, read once per run."""
    found = _CACHE.get("by_family")
    if found is None:
        found = {}
        for e in FilteredElementCollector(doc).OfClass(FamilyInstance):
            try:
                found.setdefault(eid_value(e.Symbol.Family.Id), []).append(eid_value(e.Id))
            except Exception:
                continue
        _CACHE["by_family"] = found
    return found


def workset_element_ids(workset):
    """Ids of the elements on a workset (types left out), read once per run."""
    key = u"ws_{0}".format(workset.Id.IntegerValue)
    found = _CACHE.get(key)
    if found is None:
        found = [eid_value(e.Id) for e in FilteredElementCollector(doc)
                 .WherePasses(ElementWorksetFilter(workset.Id, False)).WhereElementIsNotElementType()
                 if not isinstance(e, View)]
        _CACHE[key] = found
    return found


def type_rows_ids(cls=None, category=None):
    """type_rows() plus, for each row, the ids of the placed elements of that type."""
    col = FilteredElementCollector(doc)
    col = col.OfClass(cls) if cls is not None else col.OfCategory(category).WhereElementIsElementType()
    by_type = instances_by_type()
    found = []
    for t in col:
        c, n = cat_name(t), ename(t)
        found.append((c, n, u"{0} : Type : {1}".format(c, n), by_type.get(eid_value(t.Id), [])))
    found.sort(key=lambda r: (r[0].lower(), r[1].lower()))
    return [r[:3] for r in found], [r[3] for r in found]


def type_list(name, description, cls=None, category=None):
    """Every type of a class / category; each row selects the elements of that type."""
    rows, row_ids = type_rows_ids(cls, category)
    return count_check(name, description, rows, [u"Category", u"Type", u"Name"], row_ids=row_ids)


def coord_text(p):
    return u"{0:.0f} E/W  |  {1:.0f} N/S".format(p.X * FT_MM, p.Y * FT_MM)


def _as_id(v):
    """An element id number (Python int/long or a .NET Int32/Int64) -> int, else None."""
    if v is None or isinstance(v, (bool, basestring_type)):
        return None
    try:
        n = int(v)
    except Exception:
        return None
    return n if n == v else None


def as_ids(value):
    """None / an id / a list of ids -> a list of ints."""
    if value is None or value == u"":
        return []
    if isinstance(value, (list, tuple, set)):
        return [n for n in (_as_id(v) for v in value) if n is not None]
    n = _as_id(value)
    return [] if n is None else [n]


def selectable_ids(items):
    """Ids of placed elements among ``items``. Types, families and views are left
    out: they can't be selected in a view."""
    out = []
    for e in items:
        if isinstance(e, (ElementType, Family, View)):
            continue
        try:
            out.append(eid_value(e.Id))
        except Exception:
            continue
    return out


class Check(object):
    """One line of the report.

    ``count``   how many items the check found (None for a RESULT).
    ``ids``     element ids the whole check selects (a click on the check).
    ``row_ids`` one entry per row: an id, a list of ids or None (a click on the row).
    ``row_open`` one entry per row: the id of a view / sheet / schedule the row can open, or None.
    """

    def __init__(self, kind, name, description, result=u"", columns=None, rows=None, note=u"",
                 count=None, ids=None, row_ids=None, row_open=None):
        self.kind = kind
        self.name = name
        self.description = description
        self.result = result
        self.columns = list(columns or [])
        self.rows = list(rows or [])
        self.note = note
        self.count = count
        self.error = False
        self.row_ids = [as_ids(r) for r in (row_ids or [])]
        self.row_open = [(as_ids(r) or [None])[0] for r in (row_open or [])]
        if not self.row_ids and u"ID" in self.columns:
            at = self.columns.index(u"ID")
            self.row_ids = [as_ids(r[at]) for r in self.rows]
        if ids is None:
            seen, ids = set(), []
            for group in self.row_ids:
                for i in group:
                    if i not in seen:
                        seen.add(i)
                        ids.append(i)
        self.ids = list(ids)

    @property
    def value(self):
        """The text after 'Count: ' / 'Result: '."""
        return self.result.split(u": ", 1)[1] if u": " in self.result else self.result


def count_check(name, description, rows, columns=None, ids=None, row_ids=None, row_open=None):
    rows = list(rows)
    if not columns and ids is None:
        ids = selectable_ids(rows)
    return Check(LIST if columns else COUNT, name, description,
                 u"Count: {0}".format(number(len(rows))), columns, rows if columns else [],
                 count=len(rows), ids=ids, row_ids=row_ids if columns else None,
                 row_open=row_open if columns else None)


def passfail(name, description, bad_rows, columns, fail_note, ids=None, row_ids=None, row_open=None):
    rows = list(bad_rows)
    if rows:
        return Check(FAIL, name, description, u"Count: {0}".format(number(len(rows))),
                     columns, rows, fail_note, count=len(rows), ids=ids, row_ids=row_ids,
                     row_open=row_open)
    return Check(PASS, name, description, u"Count: 0", count=0)


def result_check(name, description, value):
    return Check(RESULT, name, description, u"Result: {0}".format(value))


# ---------------------------------------------------------------------------
# Model performance
# ---------------------------------------------------------------------------
def legend_ids():
    """Types shown by legend components, and their families: Revit calls them
    unused, but purging them empties the legends."""
    ids = set()
    for comp in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_LegendComponents):
        p = bip(comp, "LEGEND_COMPONENT")
        t = doc.GetElement(p.AsElementId()) if p is not None else None
        if t is not None:
            ids.add(eid_value(t.Id))
            family = getattr(t, "Family", None)
            if family is not None:
                ids.add(eid_value(family.Id))
    return ids


def chk_file_size():
    path = doc.PathName
    if path and os.path.exists(path):
        value = u"{0:.2f} MB".format(os.path.getsize(path) / 1048576.0)
    else:
        value = u"not saved"
    return result_check(u"File Size", u"Size of the saved model file.", value)


def chk_warnings():
    warnings = list(doc.GetWarnings())
    seen, ids = set(), []
    for w in warnings:
        try:
            for i in w.GetFailingElements():
                n = eid_value(i)
                if n not in seen:
                    seen.add(n)
                    ids.append(n)
        except Exception:
            continue
    return count_check(u"Warnings", u"Number of warnings in the model. Many unresolved warnings slow a "
                       u"model down.", warnings, ids=ids)


def chk_loadable_families():
    by_family = instances_by_family()
    fams = sorted([(ename(f), by_family.get(eid_value(f.Id), []))
                   for f in FilteredElementCollector(doc).OfClass(Family)], key=lambda r: r[0].lower())
    return count_check(u"Loadable Families", u"Every loadable and in-place family in the project. Click a "
                       u"family to select its placed instances.",
                       [(n, number(len(ids))) for n, ids in fams], [u"Name", u"Count"],
                       row_ids=[ids for n, ids in fams])


def chk_purgeable():
    found = list(doc.GetUnusedElements(set_of_ids()))
    keep = legend_ids()
    unused = [i for i in found if eid_value(i) not in keep]
    return Check(COUNT, u"Purgeable Elements", u"Elements that Purge Unused would remove (types shown "
                 u"in legends are left out). Purging keeps the file smaller and faster.",
                 u"Count: {0}".format(number(len(unused))))


def set_of_ids():
    from System.Collections.Generic import HashSet
    return HashSet[ElementId]()


def chk_object_styles():
    names = set()
    for c in doc.Settings.Categories:
        try:
            for s in c.SubCategories:
                if eid_value(s.Id) > 0:
                    names.add(ename(s))
        except Exception:
            continue
    rows = [(n,) for n in sorted(names, key=lambda s: s.lower())]
    return count_check(u"Non built-in Object Styles", u"Object styles added to the model. A long list "
                       u"usually means CAD files were imported.", rows, [u"Name"])


def chk_groups():
    model_cat = int(BuiltInCategory.OST_IOSModelGroups)
    groups = list(FilteredElementCollector(doc).OfClass(Group))
    model = [g for g in groups if g.Category is not None and eid_value(g.Category.Id) == model_cat]
    detail = [g for g in groups if g.Category is not None and eid_value(g.Category.Id) != model_cat]

    def by_type(name, description, items):
        types = {}
        for g in items:
            types.setdefault(ename(g.GroupType) if g.GroupType is not None else ename(g), []).append(
                eid_value(g.Id))
        ordered = sorted(types.items(), key=lambda x: (-len(x[1]), x[0].lower()))
        check = count_check(name, description, [(n, number(len(ids))) for n, ids in ordered],
                            [u"Type", u"Count"], row_ids=[ids for n, ids in ordered])
        check.count = len(items)
        check.result = u"Count: {0}".format(number(len(items)))
        return check

    return [by_type(u"Model Groups", u"Placed model groups, by group type.", model),
            by_type(u"Detail Groups", u"Placed detail groups, by group type.", detail)]


def chk_inplace():
    by_family = instances_by_family()
    fams = sorted([(ename(f), by_family.get(eid_value(f.Id), []))
                   for f in FilteredElementCollector(doc).OfClass(Family) if f.IsInPlace],
                  key=lambda r: r[0].lower())
    return count_check(u"In-Place Families", u"Every in-place family. Click one to select it.",
                       [(n, number(len(ids))) for n, ids in fams], [u"Name", u"Count"],
                       row_ids=[ids for n, ids in fams])


# ---------------------------------------------------------------------------
# Project settings
# ---------------------------------------------------------------------------
def chk_version():
    app = doc.Application
    return result_check(u"Revit Version", u"Revit version and build running this check.",
                        u"{0} ({1})".format(app.VersionName, app.VersionBuild))


def chk_design_options():
    rows, row_ids = [], []
    for o in FilteredElementCollector(doc).OfClass(DesignOption):
        ids = [eid_value(e.Id) for e in FilteredElementCollector(doc).WhereElementIsNotElementType()
               .WherePasses(ElementDesignOptionFilter(o.Id)) if not isinstance(e, View)]
        rows.append((ename(o), number(len(ids))))
        row_ids.append(ids)
    return count_check(u"Design Options", u"Every design option in the model. Click one to select its "
                       u"elements.", rows, [u"Name", u"Count"], row_ids=row_ids)


def chk_phases():
    phases = {}
    for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
        p = bip(e, "PHASE_CREATED")
        try:
            if p is not None and p.AsElementId() != ElementId.InvalidElementId:
                ph = doc.GetElement(p.AsElementId())
                if ph is not None:
                    phases.setdefault(ename(ph), []).append(eid_value(e.Id))
        except Exception:
            continue
    ordered = sorted(phases.items(), key=lambda x: (-len(x[1]), x[0].lower()))
    return count_check(u"Elements Per Phase", u"How many elements were created in each phase. Click a "
                       u"phase to select them.", [(number(len(ids)), name) for name, ids in ordered],
                       [u"Count", u"Name"], row_ids=[ids for name, ids in ordered])


def chk_worksets():
    if doc.IsWorkshared:
        worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
        rows = [(w.Name,) for w in worksets]
        row_ids = [workset_element_ids(w) for w in worksets]
    else:
        rows, row_ids = [(u"*Not Workshared*",)], [[]]
    return count_check(u"Worksets", u"Every user workset, or '*Not Workshared*' when worksharing "
                       u"is off. Click a workset to select its elements.", rows, [u"Name"], row_ids=row_ids)


def chk_project_info():
    rows = []
    for p in doc.ProjectInformation.Parameters:
        n = p.Definition.Name
        if not n.startswith(u"Extensions"):
            rows.append((n, param_text(p)))
    rows.sort(key=lambda r: r[0].lower())
    return count_check(u"Project Information", u"Every Project Information parameter and its value "
                       u"(Revit Extensions parameters left out).", rows, [u"Name", u"Value"])


def chk_coordinates():
    pbp_el = BasePoint.GetProjectBasePoint(doc)
    sp_el = BasePoint.GetSurveyPoint(doc)
    pbp, sp = pbp_el.Position, sp_el.Position
    pbp_id, sp_id = eid_value(pbp_el.Id), eid_value(sp_el.Id)
    angle = math.degrees(doc.ActiveProjectLocation.GetProjectPosition(XYZ.Zero).Angle)
    site = doc.SiteLocation
    rows = [(u"Project Base Point Coordinate", coord_text(pbp)),
            (u"Project Base Point Elevation", u"{0:.0f}".format(pbp.Z * FT_MM)),
            (u"Project Base Point Rotation", u"{0:.2f}°".format(angle)),
            (u"Survey Point Coordinate", coord_text(sp)),
            (u"Survey Point Elevation", u"{0:.0f}".format(sp.Z * FT_MM))]
    out = [count_check(u"Project Coordinates", u"Survey point and project base point positions, "
                       u"elevations and the angle to true north. Click a row to select that point.",
                       rows, [u"Name", u"Value"],
                       row_ids=[sp_id if r[0].startswith(u"Survey") else pbp_id for r in rows])]
    values = [(u"Survey Point - N/S", sp.Y * FT_MM), (u"Survey Point - E/W", sp.X * FT_MM),
              (u"Survey Point - Elev", sp.Z * FT_MM),
              (u"Survey Point - Latitude", math.degrees(site.Latitude)),
              (u"Survey Point - Longitude", math.degrees(site.Longitude)),
              (u"Project Base Point - N/S", pbp.Y * FT_MM), (u"Project Base Point - E/W", pbp.X * FT_MM),
              (u"Project Base Point - Elev", pbp.Z * FT_MM),
              (u"Project Base Point - Angle to True North", angle)]
    for name, value in values:
        out.append(Check(PASS, name, u"Checks the {0} value against a target. No target is set yet, so "
                         u"this always passes and shows the current value.".format(name.split(u" - ")[1]),
                         u"Result: {0:.4f}".format(value),
                         ids=[sp_id if name.startswith(u"Survey") else pbp_id]))
    return out


def chk_browser():
    rows = [(ename(b),) for b in FilteredElementCollector(doc).OfClass(BrowserOrganization)]
    return count_check(u"Browser Organization", u"Every project browser organization.", rows, [u"Name"])


def chk_volume():
    try:
        on = AreaVolumeSettings.GetAreaVolumeSettings(doc).ComputeVolumes
    except Exception:
        on = None
    return result_check(u"Volume Computations Setting", u"Whether Revit computes areas only, or areas "
                        u"and volumes.", u"Areas and Volumes" if on else u"Areas only (Volume computations off)")


# ---------------------------------------------------------------------------
# External files
# ---------------------------------------------------------------------------
def cad_type_name(i):
    return ename(doc.GetElement(i.GetTypeId()))


def cad_rows(items):
    rows = []
    for i in items:
        t = cad_type_name(i)
        rows.append((cat_name(i), t, u"{0} : {1}".format(cat_name(i), t)))
    return rows


def cad_check(name, description, items):
    items = list(items)
    return count_check(name, description, cad_rows(items), [u"Category", u"Type", u"Name"],
                       row_ids=[eid_value(i.Id) for i in items])


def imports():
    return list(FilteredElementCollector(doc).OfClass(ImportInstance))


def chk_link_method():
    rows, row_ids = [], []
    by_type = instances_by_type()
    for lt in FilteredElementCollector(doc).OfClass(RevitLinkType):
        try:
            method = u"Attachment" if lt.AttachmentType == AttachmentType.Attachment else u"Overlay"
        except Exception:
            method = u""
        rows.append((u"RVT Links : Type : {0}".format(ename(lt)), method))
        row_ids.append(by_type.get(eid_value(lt.Id), []))
    return count_check(u"Linked Revit Files and Their Link Method", u"Each Revit link and whether it is "
                       u"attached or overlaid. Click a link to select its instances.", rows,
                       [u"Name", u"Value"], row_ids=row_ids)


def chk_links_unpinned():
    bad = [(cat_name(i), ename(i), eid_value(i.Id))
           for i in FilteredElementCollector(doc).OfClass(RevitLinkInstance) if not i.Pinned]
    return passfail(u"Linked Revit Files Not Pinned in Place", u"Every Revit link should be pinned.",
                    bad, [u"Category", u"Name", u"ID"], u"These Revit links are not pinned.")


def chk_cad_linked():
    return cad_check(u"Linked CAD Files", u"CAD files that were linked, not imported.",
                     [i for i in imports() if i.IsLinked])


def chk_cad_all_views():
    rows = [(cat_name(i), cad_type_name(i), eid_value(i.Id))
            for i in imports() if i.IsLinked and not i.ViewSpecific]
    return count_check(u"Linked CAD File Visible in All Views", u"Linked CAD files placed in all views "
                       u"instead of one view.", rows, [u"Category", u"Type", u"ID"])


def chk_cad_unpinned():
    bad = [(cat_name(i), cad_type_name(i), eid_value(i.Id))
           for i in imports() if i.IsLinked and not i.Pinned]
    return passfail(u"Linked CAD File Not Pinned in Place", u"Every linked CAD file should be pinned.",
                    bad, [u"Category", u"Name", u"ID"], u"These linked CAD files are not pinned.")


def chk_cad_imported():
    items = [i for i in imports() if not i.IsLinked and not cat_name(i).lower().endswith(u".skp")]
    return cad_check(u"Imported CAD files", u"CAD files that were imported, not linked.", items)


def chk_skp():
    items = [i for i in imports() if not i.IsLinked and cat_name(i).lower().endswith(u".skp")]
    return cad_check(u"Imported SKP files", u"SketchUp files that were imported.", items)


def chk_raster():
    by_type = instances_by_type()
    images = list(FilteredElementCollector(doc).OfClass(ImageType))
    rows = [(cat_name(t), ename(t), u"{0} : {1}".format(cat_name(t), ename(t))) for t in images]
    return count_check(u"Raster Images", u"Every raster image in the model. Click one to select where "
                       u"it is placed.", rows, [u"Category", u"Type", u"Name"],
                       row_ids=[by_type.get(eid_value(t.Id), []) for t in images])


# ---------------------------------------------------------------------------
# Datum and location elements
# ---------------------------------------------------------------------------
def shared_levels_workset():
    for w in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
        if u"shared levels" in w.Name.lower():
            return w
    return None


def chk_levels():
    return count_check(u"Levels", u"Number of levels.", list(FilteredElementCollector(doc).OfClass(Level)))


def chk_level_types():
    return type_list(u"Level Types", u"Every level type. Click one to select its levels.", LevelType)


def chk_grids():
    return count_check(u"Grids", u"Number of grids.", list(FilteredElementCollector(doc).OfClass(Grid)))


def chk_grid_types():
    return type_list(u"Grid Types", u"Every grid type. Click one to select its grids.", GridType)


def chk_wrong_on_shared():
    rows = []
    w = shared_levels_workset() if doc.IsWorkshared else None
    if w is not None:
        col = FilteredElementCollector(doc).WhereElementIsNotElementType() \
            .WherePasses(ElementWorksetFilter(w.Id, False))
        for e in col:
            if isinstance(e, (Level, Grid, ReferencePlane)) or e.Category is None or e.ViewSpecific:
                continue
            rows.append((cat_name(e), ename(e), eid_value(e.Id)))
    return count_check(u"Wrong Elements on Shared Levels and Grids", u"Elements other than levels, grids "
                       u"and reference planes on the 'Shared Levels and Grids' workset.",
                       rows, [u"Category", u"Name", u"ID"])


def chk_levels_wrong_workset():
    bad = []
    if doc.IsWorkshared:
        table = doc.GetWorksetTable()
        datums = list(FilteredElementCollector(doc).OfClass(Level)) + \
            list(FilteredElementCollector(doc).OfClass(Grid))
        for e in datums:
            w = table.GetWorkset(e.WorksetId)
            if u"shared levels" not in w.Name.lower():
                bad.append((cat_name(e), ename(e), w.Name, eid_value(e.Id)))
    return passfail(u"Levels and Grids on Wrong Workset", u"Levels and grids should sit on the 'Shared "
                    u"Levels and Grids' workset.", bad, [u"Category", u"Name", u"Workset", u"ID"],
                    u"These levels and grids are not on the Shared Levels and Grids workset.")


SPATIAL_COLUMNS = [u"Number", u"Name", u"Level", u"Area", u"ID"]


def spatial_row(s):
    """(number, name, level, area, id) of a room, space or area."""
    try:
        level = s.Level.Name if s.Level is not None else u""
    except Exception:
        level = u""
    area = param_text(bip(s, "ROOM_AREA")) if s.Location is not None else u"not placed"
    return (param_text(bip(s, "ROOM_NUMBER")), param_text(bip(s, "ROOM_NAME")) or ename(s), level,
            area, eid_value(s.Id))


def spatial_order(items):
    return sorted(items, key=lambda s: (param_text(bip(s, "ROOM_NUMBER")).lower(), eid_value(s.Id)))


def spatial_checks(kind, category):
    items = spatial_order(instances(category))
    label = kind + u"s"
    lower = label.lower()
    out = [count_check(label, u"Every {0} with its number, name, level and area. Click one to select "
                       u"it.".format(kind.lower()), [spatial_row(s) for s in items], SPATIAL_COLUMNS)]
    unplaced = [spatial_row(s) for s in items if s.Location is None]
    out.append(passfail(u"Unplaced " + label, u"{0} that exist but are not placed.".format(label),
                        unplaced, SPATIAL_COLUMNS, u"These {0} are not placed.".format(lower)))
    bad = []
    for s in items:
        if s.Location is None:
            continue
        try:
            if s.Area <= 1e-9:
                bad.append(spatial_row(s))
        except Exception:
            pass
    out.append(passfail(u"Redundant and Unenclosed " + label, u"Placed {0} with no area: redundant or not "
                        u"enclosed.".format(lower), bad, SPATIAL_COLUMNS,
                        u"These {0} are redundant or not enclosed.".format(lower)))
    numbers = {}
    for s in items:
        p = bip(s, "ROOM_NUMBER")
        v = p.AsString() if p is not None else None
        if v:
            numbers.setdefault(v, []).append(eid_value(s.Id))
    dup = sorted([(num, ids) for num, ids in numbers.items() if len(ids) > 1], key=lambda x: x[0])
    out.append(passfail(u"Unique {0} Number".format(kind), u"Every {0} number should be used once.".format(
        kind.lower()), [(number(len(ids)), num) for num, ids in dup], [u"Count", u"Number"],
        u"These {0} numbers are used more than once.".format(kind.lower()),
        row_ids=[ids for num, ids in dup]))
    return out


def chk_rooms():
    return spatial_checks(u"Room", BuiltInCategory.OST_Rooms)


def chk_spaces():
    return spatial_checks(u"Space", BuiltInCategory.OST_MEPSpaces)


def chk_area_schemes():
    by_scheme = {}
    for a in instances(BuiltInCategory.OST_Areas):
        try:
            by_scheme.setdefault(eid_value(a.AreaScheme.Id), []).append(eid_value(a.Id))
        except Exception:
            continue
    schemes = list(FilteredElementCollector(doc).OfClass(AreaScheme))
    rows = [(ename(s), number(len(by_scheme.get(eid_value(s.Id), [])))) for s in schemes]
    return count_check(u"Area Space Schemes", u"Every area scheme and how many areas it holds. Click a "
                       u"scheme to select its areas.", rows, [u"Name", u"Count"],
                       row_ids=[by_scheme.get(eid_value(s.Id), []) for s in schemes])


def chk_areas():
    items = spatial_order(instances(BuiltInCategory.OST_Areas))
    return [count_check(u"Areas", u"Every area with its number, name, level and area. Click one to "
                        u"select it.", [spatial_row(a) for a in items], SPATIAL_COLUMNS),
            passfail(u"Areas Not Placed", u"Areas that exist but are not placed.",
                     [spatial_row(a) for a in items if a.Location is None],
                     SPATIAL_COLUMNS, u"These areas are not placed.")]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
_VIEW_CACHE = {}


def view_sets():
    """(plain views, sheets, schedules, templates, ids of views placed on sheets), read once."""
    if not _VIEW_CACHE:
        everything = list(FilteredElementCollector(doc).OfClass(View))
        views = [v for v in everything if not v.IsTemplate]
        sheets = [v for v in views if isinstance(v, ViewSheet)]
        schedules = [v for v in views if isinstance(v, ViewSchedule)]
        skip_types = (ViewType.ProjectBrowser, ViewType.SystemBrowser, ViewType.Internal, ViewType.Undefined)
        plain = [v for v in views if not isinstance(v, (ViewSheet, ViewSchedule)) and v.ViewType not in skip_types]
        placed = set()
        on_sheet = {}
        for s in sheets:
            for pid in s.GetAllPlacedViews():
                placed.add(eid_value(pid))
                on_sheet.setdefault(eid_value(pid), []).append(s.SheetNumber)
        for ssi in FilteredElementCollector(doc).OfClass(ScheduleSheetInstance):
            try:
                if ssi.IsTitleblockRevisionSchedule:
                    continue
                sheet = doc.GetElement(ssi.OwnerViewId)
                if isinstance(sheet, ViewSheet):
                    on_sheet.setdefault(eid_value(ssi.ScheduleId), []).append(sheet.SheetNumber)
            except Exception:
                continue
        _VIEW_CACHE.update(plain=plain, sheets=sheets, schedules=schedules,
                           templates=[v for v in everything if v.IsTemplate], placed=placed,
                           on_sheet=on_sheet)
    return _VIEW_CACHE


VIEW_TYPE_NAMES = {
    "ThreeD": u"3D View", "EngineeringPlan": u"Structural Plan", "DraftingView": u"Drafting View",
    "Detail": u"Detail View", "CostReport": u"Cost Report", "LoadsReport": u"Loads Report",
    "PresureLossReport": u"Pressure Loss Report", "PanelSchedule": u"Panel Schedule",
    "ColumnSchedule": u"Graphical Column Schedule", "DrawingSheet": u"Sheet",
}


def view_type_name(v):
    raw = u"{0}".format(v.ViewType)
    return VIEW_TYPE_NAMES.get(raw) or re.sub(r"(?<=[a-z])(?=[A-Z])", u" ", raw)


def view_list(name, description, views, show_type=True):
    """A list check of views: each row selects the view and can open it."""
    on_sheet = view_sets()["on_sheet"]
    views = sorted(views, key=lambda v: (view_type_name(v).lower(), ename(v).lower()))
    rows = []
    for v in views:
        numbers = sorted(set(on_sheet.get(eid_value(v.Id), [])))
        sheets = (u"On " + u", ".join(numbers)) if numbers else u"Not on a sheet"
        row = (view_type_name(v), ename(v), sheets, eid_value(v.Id))
        rows.append(row if show_type else row[1:])
    columns = [u"Type", u"Name", u"Sheet", u"ID"] if show_type else [u"Name", u"Sheet", u"ID"]
    ids = [eid_value(v.Id) for v in views]
    return count_check(name, description, rows, columns, row_ids=ids, row_open=ids)


def sheet_list(name, description, sheets):
    sheets = sorted(sheets, key=lambda s: (s.SheetNumber or u"").lower())
    rows = [(s.SheetNumber, ename(s), eid_value(s.Id)) for s in sheets]
    ids = [eid_value(s.Id) for s in sheets]
    # a placeholder sheet has no view to open
    opens = [None if s.IsPlaceholder else eid_value(s.Id) for s in sheets]
    return count_check(name, description, rows, [u"Number", u"Name", u"ID"], row_ids=ids, row_open=opens)


def chk_view_counts():
    s = view_sets()
    schedules = [v for v in s["schedules"] if not getattr(v, "IsTitleblockRevisionSchedule", False)]
    hint = u" Click one to select it, double-click or click Open to open it."
    return [view_list(u"Views", u"Every view (sheets and schedules not included)." + hint, s["plain"]),
            view_list(u"Schedules", u"Every schedule (revision schedules inside title blocks left out)." +
                      hint, schedules, show_type=False),
            sheet_list(u"Sheets", u"Every sheet, placeholders included." + hint, s["sheets"]),
            sheet_list(u"Placeholder Sheets", u"Sheets that are only placeholders (no drawing area). "
                       u"Click one to select it.", [x for x in s["sheets"] if x.IsPlaceholder])]


def chk_templates():
    rows = [(u"Views", u"{0}".format(t.ViewType), ename(t), u"Views : {0} : {1}".format(t.ViewType, ename(t)))
            for t in view_sets()["templates"]]
    return count_check(u"View Templates", u"Every view template.", rows,
                       [u"Category", u"Family", u"Type", u"Name"])


def chk_hidden_elements():
    rows, ids = [], []
    for v in sorted(view_sets()["plain"], key=lambda x: ename(x).lower()):
        try:
            n = len([e for e in FilteredElementCollector(doc, v.Id).WhereElementIsNotElementType()
                     if e.IsHidden(v)])
        except Exception:
            n = 0
        if n:
            rows.append((number(n), ename(v)))
            ids.append(eid_value(v.Id))
    return count_check(u"Views With Hidden Model Elements", u"Views with elements hidden one by one "
                       u"(Hide in View > Elements). Click a view to select it, double-click or click Open "
                       u"to open it.", rows, [u"Count", u"Name"], row_ids=ids, row_open=ids)


def chk_view_placement():
    s = view_sets()
    plain, placed = s["plain"], s["placed"]
    hint = u" Click one to select it, double-click or click Open to open it."
    return [view_list(u"Views With No View Template", u"Views with no view template." + hint,
                      [v for v in plain if eid_value(v.ViewTemplateId) < 0]),
            view_list(u"Views Not On Sheets", u"Views that are not placed on any sheet." + hint,
                      [v for v in plain if eid_value(v.Id) not in placed and v.CanBePrinted]),
            view_list(u"Views On Sheets With No View Template", u"Views on sheets with no view "
                      u"template." + hint, [v for v in plain if eid_value(v.Id) in placed and
                                            eid_value(v.ViewTemplateId) < 0])]


def chk_navis_view():
    navis = [v for v in view_sets()["plain"] if isinstance(v, View3D) and u"navis" in ename(v).lower()]
    name = u"Navisworks Export View"
    description = u"There should be a 3D view with 'Navis' in its name for NWC export."
    if not navis:
        return passfail(name, description, [(u"3D View", u"(none)", u"")], [u"Category", u"Name", u"ID"],
                        u"No 3D view named for Navisworks export was found.")
    ids = [eid_value(v.Id) for v in navis]
    return Check(PASS, name, description + u" Click the view to select it, double-click or click Open to "
                 u"open it.", u"Count: 0", [u"Name", u"ID"], [(ename(v), eid_value(v.Id)) for v in navis],
                 count=0, row_ids=ids, row_open=ids)


def chk_legends_scopes():
    legends = [v for v in view_sets()["plain"] if v.ViewType == ViewType.Legend]
    boxes = instances(BuiltInCategory.OST_VolumeOfInterest)
    scopes = [(cat_name(s), ename(s)) for s in boxes]
    return [view_list(u"Symbol Legends and General Notes", u"Every legend view. Click one to select it, "
                      u"double-click or click Open to open it.", legends, show_type=False),
            count_check(u"Scope Boxes", u"Every scope box.", scopes, [u"Category", u"Name"],
                        row_ids=[eid_value(s.Id) for s in boxes])]


# ---------------------------------------------------------------------------
# Model elements
# ---------------------------------------------------------------------------
def instance_row(e):
    return (cat_name(e), e.Symbol.Family.Name, ename(e.Symbol), ename(e), eid_value(e.Id))


def chk_assemblies():
    rows = [(cat_name(a), ename(a), eid_value(a.Id)) for a in FilteredElementCollector(doc).OfClass(AssemblyInstance)]
    return count_check(u"Assemblies", u"Every assembly in the model.", rows, [u"Category", u"Name", u"ID"])


def chk_generic_models():
    return type_list(u"Generic Models", u"Every generic model type. Click one to select its instances.",
                     category=BuiltInCategory.OST_GenericModel)


def chk_duplicates():
    seen, dup = set(), []
    for e in FilteredElementCollector(doc).OfClass(FamilyInstance):
        loc = e.Location
        if not isinstance(loc, LocationPoint):
            continue
        p = loc.Point
        key = (eid_value(e.GetTypeId()), round(p.X, 3), round(p.Y, 3), round(p.Z, 3))
        if key in seen:
            dup.append(instance_row(e))
        seen.add(key)
    return passfail(u"Duplicate Modeled Elements", u"Family instances of the same type at the same point.",
                    dup, [u"Category", u"Family", u"Type", u"Name", u"ID"],
                    u"These elements are duplicated at one location.")


def chk_mirrored():
    bad = [instance_row(e) for e in FilteredElementCollector(doc).OfClass(FamilyInstance) if e.Mirrored]
    return passfail(u"Mirrored Elements", u"Family instances that have been mirrored.", bad,
                    [u"Category", u"Family", u"Type", u"Name", u"ID"], u"These elements have been mirrored.")


def chk_workset_counts():
    if doc.IsWorkshared:
        rows, row_ids = [], []
        for w in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            n = FilteredElementCollector(doc).WherePasses(ElementWorksetFilter(w.Id, False)) \
                .WhereElementIsNotElementType().GetElementCount()
            rows.append((number(n), w.Name))
            row_ids.append(workset_element_ids(w))
    else:
        rows, row_ids = [(u"", u"*Not Workshared*")], [[]]
    return count_check(u"Worksets and Elements", u"Every user workset and how many elements it holds, or "
                       u"'*Not Workshared*'. Click a workset to select its elements.", rows,
                       [u"Count", u"Name"], row_ids=row_ids)


def chk_totals():
    model_lines = [c for c in FilteredElementCollector(doc).OfClass(CurveElement) if isinstance(c, ModelCurve)]
    model, analytical = [], []
    for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
        c = e.Category
        if c is None or e.ViewSpecific:
            continue
        if c.CategoryType == CategoryType.Model:
            model.append(e)
        elif c.CategoryType == CategoryType.AnalyticalModel:
            analytical.append(e)
    return [count_check(u"Total Model Lines", u"Number of model lines.", model_lines),
            count_check(u"Total Model Elements", u"Number of model category elements.", model),
            count_check(u"Total Analytical Model Elements", u"Number of analytical model elements.", analytical)]


def family_list(name, cls=None, category=None):
    def check():
        return type_list(name, u"Every type in {0}. Click a type to select its elements.".format(
            name.lower()), cls, category)
    return (name, check)


ARCH_LISTS = [
    family_list(u"Ceiling Families", CeilingType), family_list(u"Curtain System", CurtainSystemType),
    family_list(u"Curtain Wall Mullion Families", MullionType), family_list(u"Floor Families", FloorType),
    family_list(u"Railing Families", category=BuiltInCategory.OST_StairsRailing),
    family_list(u"Ramp Families", category=BuiltInCategory.OST_Ramps),
    family_list(u"Roof Families", RoofType), family_list(u"Site Families", category=BuiltInCategory.OST_Site),
    family_list(u"Stair Families", category=BuiltInCategory.OST_Stairs), family_list(u"Wall Families", WallType),
]

STRUCT_LISTS = [
    family_list(u"Floor Families", FloorType),
    family_list(u"Foundation Families", category=BuiltInCategory.OST_StructuralFoundation),
    family_list(u"Rebar Families", category=BuiltInCategory.OST_Rebar), family_list(u"Wall Families", WallType),
]


def system_network_ids(system):
    """Ids of the ducts / pipes / fittings that make up an MEP system."""
    for attr in ("DuctNetwork", "PipingNetwork"):
        try:
            network = getattr(system, attr)
        except Exception:
            continue
        if network is None:
            continue
        out = []
        for e in network:
            try:
                out.append(eid_value(e.Id))
            except Exception:
                continue
        return out
    return []


def unconnected(name, cls, word):
    def check():
        bad, row_ids = [], []
        for s in FilteredElementCollector(doc).OfClass(cls):
            try:
                if s.IsWellConnected is False:
                    bad.append((cat_name(s), ename(s), eid_value(s.Id)))
                    row_ids.append(system_network_ids(s))
            except Exception:
                pass
        return passfail(name, u"{0} systems should be well connected. Click a system to select its "
                        u"elements.".format(word.capitalize()), bad, [u"Category", u"Name", u"ID"],
                        u"These {0} systems are not connected.".format(word), row_ids=row_ids)
    return (name, check)


ELECTRICAL_CATEGORIES = ("OST_ElectricalFixtures", "OST_ElectricalEquipment", "OST_LightingFixtures",
                         "OST_LightingDevices", "OST_FireAlarmDevices", "OST_DataDevices",
                         "OST_CommunicationDevices", "OST_SecurityDevices", "OST_NurseCallDevices",
                         "OST_TelephoneDevices")


def chk_electrical():
    bad = []
    for name in ELECTRICAL_CATEGORIES:
        bic = getattr(BuiltInCategory, name, None)
        if bic is None:
            continue
        for e in instances(bic):
            if not isinstance(e, FamilyInstance):
                continue
            panel = param_text(bip(e, "RBS_ELEC_CIRCUIT_PANEL_PARAM"))
            circuit = param_text(bip(e, "RBS_ELEC_CIRCUIT_NUMBER"))
            if not panel or not circuit:
                bad.append(instance_row(e))
    return passfail(u"Electrical Systems That Are Not Connected", u"Electrical elements with a blank Panel "
                    u"or Circuit Number.", bad, [u"Category", u"Family", u"Type", u"Name", u"ID"],
                    u"These electrical elements have a blank Panel or Circuit Number.")


MEP_CHECKS = [
    family_list(u"Duct Families", DuctType), family_list(u"Duct System Families", MechanicalSystemType),
    unconnected(u"Duct Systems That Are Not Connected", MechanicalSystem, u"duct"),
    family_list(u"Flex Duct Families", FlexDuctType), family_list(u"Flex Pipe Families", FlexPipeType),
    family_list(u"Pipe Families", PipeType), family_list(u"Piping System Families", PipingSystemType),
    unconnected(u"Piping Systems That Are Not Connected", PipingSystem, u"piping"),
    (u"Electrical Systems That Are Not Connected", chk_electrical),
]


# ---------------------------------------------------------------------------
# Annotative elements
# ---------------------------------------------------------------------------
def named_types(types):
    """(rows, row_ids): each type's name and the ids of the elements using it."""
    by_type = instances_by_type()
    types = sorted(types, key=lambda t: ename(t).lower())
    return [(ename(t), ename(t)) for t in types], [by_type.get(eid_value(t.Id), []) for t in types]


def two_names(cls):
    return named_types(list(FilteredElementCollector(doc).OfClass(cls)))


def line_style_rows(lines):
    """(rows, row_ids): every line style and the model / detail lines drawn with it."""
    by_style = {}
    for c in FilteredElementCollector(doc).OfClass(CurveElement):
        try:
            by_style.setdefault(eid_value(c.LineStyle.Id), []).append(eid_value(c.Id))
        except Exception:
            continue
    rows, row_ids = [], []
    for s in sorted(lines.SubCategories, key=lambda x: ename(x).lower()):
        ids = []
        for kind in (GraphicsStyleType.Projection, GraphicsStyleType.Cut):
            try:
                gs = s.GetGraphicsStyle(kind)
                if gs is not None:
                    ids += by_style.get(eid_value(gs.Id), [])
            except Exception:
                continue
        rows.append((ename(s),))
        row_ids.append(ids)
    return rows, row_ids


def chk_styles():
    lines = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    text_rows, text_ids = two_names(TextNoteType)
    dim_rows, dim_ids = two_names(DimensionType)
    line_rows, line_ids = line_style_rows(lines)
    region_rows, region_ids = type_rows_ids(FilledRegionType)
    return [count_check(u"Text Styles", u"Every text type. Click one to select the text notes using it.",
                        text_rows, [u"Type", u"Name"], row_ids=text_ids),
            count_check(u"Dimension Styles", u"Every dimension type. Click one to select the dimensions "
                        u"using it.", dim_rows, [u"Type", u"Name"], row_ids=dim_ids),
            count_check(u"Line Patterns", u"Every line pattern.",
                        [(ename(p),) for p in FilteredElementCollector(doc).OfClass(LinePatternElement)], [u"Name"]),
            count_check(u"Line Styles", u"Every line style. Click one to select the lines drawn with it.",
                        line_rows, [u"Name"], row_ids=line_ids),
            count_check(u"Fill Patterns", u"Every fill pattern.",
                        [(ename(p),) for p in FilteredElementCollector(doc).OfClass(FillPatternElement)], [u"Name"]),
            count_check(u"Filled Regions", u"Every filled region type. Click one to select its filled "
                        u"regions.", region_rows, [u"Category", u"Type", u"Name"], row_ids=region_ids)]


def tag_types(category):
    return named_types(list(FilteredElementCollector(doc).OfCategory(category).WhereElementIsElementType()))


def chk_view_annotation():
    elev_rows, elev_ids = tag_types(BuiltInCategory.OST_ElevationMarks)
    sect_rows, sect_ids = tag_types(BuiltInCategory.OST_SectionHeads)
    return [count_check(u"Elevation Tags", u"Every elevation tag type.", elev_rows, [u"Type", u"Name"],
                        row_ids=elev_ids),
            count_check(u"Section Tags", u"Every section tag type.", sect_rows, [u"Type", u"Name"],
                        row_ids=sect_ids),
            count_check(u"Matchlines", u"Number of matchlines.", instances(BuiltInCategory.OST_Matchline)),
            count_check(u"View References", u"Every view reference.",
                        [(cat_name(v), ename(v), eid_value(v.Id)) for v in instances(BuiltInCategory.OST_ReferenceViewer)],
                        [u"Category", u"Name", u"ID"])]


def chk_keynotes():
    keys = {}
    for k in instances(BuiltInCategory.OST_KeynoteTags):
        p = bip(k, "KEY_VALUE")
        v = p.AsString() if p is not None else None
        keys.setdefault(v if v else u"(blank)", []).append(eid_value(k.Id))
    ordered = sorted(keys.items(), key=lambda x: (-len(x[1]), x[0].lower()))
    return count_check(u"Keynotes", u"Every keynote value and how often it is used.",
                       [(number(len(ids)), k) for k, ids in ordered], [u"Count", u"Name"],
                       row_ids=[ids for k, ids in ordered])


def chk_annotation_totals():
    detail = [c for c in FilteredElementCollector(doc).OfClass(CurveElement) if isinstance(c, DetailCurve)]
    notes = [e for e in FilteredElementCollector(doc).WhereElementIsNotElementType()
             if e.Category is not None and e.Category.CategoryType == CategoryType.Annotation]
    return [count_check(u"Total Detail Lines", u"Number of detail lines.", detail),
            count_check(u"Total Annotative Elements", u"Number of annotation category elements.", notes)]


# ---------------------------------------------------------------------------
# The report tree: (title, description, [(label, check) or subsection])
# ---------------------------------------------------------------------------
SECTIONS = [
    (u"Model Performance", u"Things that build up while a model is worked on and slow it down.", [
        (u"File Size", chk_file_size), (u"Warnings", chk_warnings),
        (u"Loadable Families", chk_loadable_families), (u"Purgeable Elements", chk_purgeable),
        (u"Non built-in Object Styles", chk_object_styles), (u"Groups", chk_groups),
        (u"In-Place Families", chk_inplace)]),
    (u"Project Settings", u"Version, phases, worksets, project information, coordinates and browser "
                          u"organization.", [
        (u"Revit Version", chk_version), (u"Design Options", chk_design_options),
        (u"Elements Per Phase", chk_phases), (u"Worksets", chk_worksets),
        (u"Project Information", chk_project_info), (u"Project Coordinates", chk_coordinates),
        (u"Browser Organization", chk_browser), (u"Volume Computations Setting", chk_volume)]),
    (u"External Files", u"Linked and imported Revit, CAD, SketchUp and image files.", [
        (u"Link Method", chk_link_method), (u"Revit Links Not Pinned", chk_links_unpinned),
        (u"Linked CAD Files", chk_cad_linked), (u"Linked CAD in All Views", chk_cad_all_views),
        (u"Linked CAD Not Pinned", chk_cad_unpinned), (u"Imported CAD files", chk_cad_imported),
        (u"Imported SKP files", chk_skp), (u"Raster Images", chk_raster)]),
    (u"Datum and Location Elements", u"Levels and grids, their types, and whether they sit on the right "
                                     u"workset.", [
        (u"Levels", chk_levels), (u"Level Types", chk_level_types), (u"Grids", chk_grids),
        (u"Grid Types", chk_grid_types), (u"Wrong Elements on Shared Levels and Grids", chk_wrong_on_shared),
        (u"Levels and Grids on Wrong Workset", chk_levels_wrong_workset)]),
    (u"Rooms, Spaces and Areas", u"Rooms, spaces and areas: placed, enclosed and numbered once, with their "
                                 u"areas.", [
        (u"Rooms", u"Rooms: placed, enclosed and numbered once.", [(u"Rooms", chk_rooms)]),
        (u"Spaces", u"Spaces: placed, enclosed and numbered once.", [(u"Spaces", chk_spaces)]),
        (u"Areas", u"Area schemes and areas.", [(u"Area Space Schemes", chk_area_schemes), (u"Areas", chk_areas)])]),
    (u"Views", u"Views, schedules, sheets, templates and legends.", [
        (u"View Counts", chk_view_counts), (u"View Templates", chk_templates),
        (u"Views With Hidden Model Elements", chk_hidden_elements), (u"View Placement", chk_view_placement),
        (u"Navisworks Export View", chk_navis_view), (u"Legends and Scope Boxes", chk_legends_scopes)]),
    (u"Model Elements", u"Model elements and the system families of every discipline.", [
        (u"All Discipline Families", u"Elements common to every discipline.", [
            (u"Assemblies", chk_assemblies), (u"Generic Models", chk_generic_models),
            (u"Duplicate Modeled Elements", chk_duplicates), (u"Mirrored Elements", chk_mirrored),
            (u"Worksets and Elements", chk_workset_counts), (u"Totals", chk_totals)]),
        (u"Arch System Families", u"Architectural system families.", ARCH_LISTS),
        (u"MEP System Families", u"MEP system families and system connections.", MEP_CHECKS),
        (u"Structural System Families", u"Structural system families.", STRUCT_LISTS)]),
    (u"Annotative Elements", u"Styles, patterns, tags, keynotes and annotation totals.", [
        (u"Styles and Patterns", chk_styles), (u"View Annotation", chk_view_annotation),
        (u"Keynotes", chk_keynotes), (u"Annotation Totals", chk_annotation_totals)]),
]


def is_group(item):
    """A (sub)section is (title, description, list); a check is (label, function)."""
    return len(item) == 3 and isinstance(item[2], list)


def section_titles():
    return [t for t, _d, _c in SECTIONS]


def find_section(title):
    for item in SECTIONS:
        if item[0] == title:
            return item
    raise KeyError(title)


def check_functions(items):
    """Every (label, function) in the tree, in order (for the progress bar)."""
    out = []
    for item in items:
        if is_group(item):
            out += check_functions(item[2])
        else:
            out.append(item)
    return out


def run_check(label, func):
    """One check; an API failure becomes a RESULT line instead of losing the report."""
    try:
        found = func()
    except Exception as ex:
        failed = Check(RESULT, label, u"This check could not run.", u"Error: {0}".format(ex))
        failed.error = True
        return [failed]
    return found if isinstance(found, list) else [found]


def run_sections(document, titles=None, bar=None):
    """Run the checks of the named sections (all when ``titles`` is None) on ``document``.

    Returns [(title, description, [Check or (title, description, [...])])], or None
    when the progress bar was cancelled. ``bar`` is a pyRevit ProgressBar or None.
    """
    global doc
    doc = document
    _VIEW_CACHE.clear()
    _CACHE.clear()
    chosen = [item for item in SECTIONS if titles is None or item[0] in titles]
    total = max(1, len(check_functions(chosen)))
    done = [0]
    cancelled = [False]

    def build(items):
        out = []
        for item in items:
            if cancelled[0]:
                break
            if is_group(item):
                title, description, children = item
                out.append((title, description, build(children)))
                continue
            out += run_check(item[0], item[1])
            done[0] += 1
            if bar is not None:
                bar.update_progress(done[0], total)
                if bar.cancelled:
                    cancelled[0] = True
        return out

    try:
        tree = build(chosen)
    finally:
        _VIEW_CACHE.clear()     # don't keep views of this model alive
        _CACHE.clear()
        doc = None
    return None if cancelled[0] else tree


def flat_checks(items):
    for item in items:
        if isinstance(item, Check):
            yield item
        else:
            for c in flat_checks(item[2]):
                yield c


def breakdown(checks):
    """(checks, passed, failed, others, pass rate or None)."""
    checks = list(checks)
    n = len(checks)
    p = len([c for c in checks if c.kind == PASS])
    f = len([c for c in checks if c.kind == FAIL])
    rate = int(round(100.0 * p / (p + f))) if (p + f) else None
    return n, p, f, n - p - f, rate

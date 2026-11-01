# -*- coding: utf-8 -*-
"""DLC Export Sheets - Revit API layer (Revit 2025/2026, IronPython 2.7).

Everything that talks to Revit lives here: collecting sheets/views, reading
parameters (built-in, project, shared, title block, project info) on demand,
building PDF/DWG options, turning off temporary view modes and running the
export jobs.

Speed (v1.1):
  * batch export - several sheets per Revit export call (PDF: Combine=False
    with a Sheet Number naming rule; DWG: one call with a known prefix). The
    files are matched back to sheets and renamed to the user's naming rule;
    anything that cannot be matched with certainty is re-exported one by one.
  * staging - Revit writes into a fresh local temp folder; finished files are
    then moved to the destination (OneDrive/network folders are slow to write).
  * lazy parameters - values are only read for the fields the naming rule uses.
"""
import ntpath
import os
import shutil
import tempfile
import time

try:
    import clr  # noqa: F401
    clr.AddReference("RevitAPI")
except Exception:  # pragma: no cover - already loaded inside pyRevit
    pass

from Autodesk.Revit import DB
from System.Collections.Generic import List

import dlc_export_core as core

FEET_TO_MM = 304.8
DWG_DEFAULT_SETUP = u"<In-session default>"

SKIP_VIEW_TYPES = set(["ProjectBrowser", "SystemBrowser", "Internal", "Undefined",
                       "DrawingSheet"])


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def eid_int(eid):
    """ElementId -> int (Revit 2024+ uses .Value; IntegerValue is removed in 2026)."""
    v = getattr(eid, "Value", None)
    if v is None:
        v = getattr(eid, "IntegerValue", -1)
    try:
        return int(v)
    except Exception:
        return -1


_EIDS = {}   # int -> the ElementId object Revit gave us (no re-construction needed)


def _remember(eid):
    _EIDS[eid_int(eid)] = eid
    return eid_int(eid)


def make_id(value):
    eid = _EIDS.get(value)
    if eid is not None:
        return eid
    try:
        from System import Int64   # Revit 2024+: ElementId(Int64)
        return DB.ElementId(Int64(value))
    except Exception:
        return DB.ElementId(int(value))


def el_name(el):
    try:
        return core.to_text(DB.Element.Name.GetValue(el))
    except Exception:
        try:
            return core.to_text(el.Name)
        except Exception:
            return u""


def param_text(doc, p):
    """Readable text of a parameter whatever its storage type."""
    try:
        if p is None or not p.HasValue:
            return u""
        st = p.StorageType
        if st == DB.StorageType.String:
            return core.to_text(p.AsString())
        txt = p.AsValueString()
        if txt:
            return core.to_text(txt)
        if st == DB.StorageType.Integer:
            return core.to_text(p.AsInteger())
        if st == DB.StorageType.Double:
            return core.to_text(round(p.AsDouble(), 4))
        if st == DB.StorageType.ElementId:
            el = doc.GetElement(p.AsElementId())
            return el_name(el) if el is not None else u""
    except Exception:
        pass
    return u""


def _param_names(element, source, catalog):
    if element is None:
        return
    try:
        params = list(element.Parameters)
    except Exception:
        return
    for p in params:
        try:
            name = core.to_text(p.Definition.Name)
        except Exception:
            continue
        if name:
            catalog.add((source, name))


def _lookup(doc, element, name):
    """Value of the named parameter; when several share the name, the first non-empty."""
    if element is None:
        return u""
    first = None
    try:
        first = element.LookupParameter(name)
    except Exception:
        first = None
    txt = param_text(doc, first)
    if txt:
        return txt
    try:
        for p in element.Parameters:
            if core.to_text(p.Definition.Name) == name:
                t = param_text(doc, p)
                if t:
                    return t
    except Exception:
        pass
    return txt


class LazyValues(object):
    """Field values for one sheet/view, read from Revit only when first asked for."""

    def __init__(self, doc, sources, shared):
        self._doc = doc
        self._src = sources          # {"sheet": el, "titleblock": el, "view": el}
        self._shared = shared        # cache shared by all items (project information)
        self._cache = {}

    def _load(self, key):
        source, _sep, name = core.to_text(key).partition(u"|")
        if source == u"project":
            if key not in self._shared:
                self._shared[key] = _lookup(self._doc, self._doc.ProjectInformation, name)
            return self._shared[key]
        return _lookup(self._doc, self._src.get(source), name)

    def get(self, key, default=u""):
        if key not in self._cache:
            try:
                self._cache[key] = self._load(key)
            except Exception:
                self._cache[key] = u""
        val = self._cache[key]
        return default if val is None else val

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self._cache[key] = value

    def __contains__(self, key):
        return key in self._cache


def bip_text(doc, element, bip_name):
    try:
        bip = getattr(DB.BuiltInParameter, bip_name)
        return param_text(doc, element.get_Parameter(bip))
    except Exception:
        return u""


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def project_info(doc):
    info = {"number": u"", "name": u"", "model": u"", "user": u""}
    try:
        pi = doc.ProjectInformation
        info["number"] = core.to_text(pi.Number)
        info["name"] = core.to_text(pi.Name)
    except Exception:
        pass
    try:
        info["model"] = core.to_text(doc.Title)
    except Exception:
        pass
    try:
        info["user"] = core.to_text(doc.Application.Username)
    except Exception:
        pass
    if not info["user"]:
        info["user"] = core.to_text(os.environ.get("USERNAME", u""))
    return info


def _title_blocks_by_sheet(doc):
    out = {}
    try:
        tbs = DB.FilteredElementCollector(doc) \
            .OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
            .WhereElementIsNotElementType().ToElements()
    except Exception:
        return out
    for tb in tbs:
        try:
            key = eid_int(tb.OwnerViewId)
        except Exception:
            continue
        out.setdefault(key, tb)   # first title block wins
    return out


SPECIAL_FIELDS = ["Model Name", "User Name", "Date (YYYY-MM-DD)", "Date (YYYYMMDD)",
                  "Time (HHMM)"]


def _special_values(values, project):
    values[core.field_key("special", "Model Name")] = project.get("model", u"")
    values[core.field_key("special", "User Name")] = project.get("user", u"")
    for f in SPECIAL_FIELDS[2:]:
        values[core.field_key("special", f)] = u""      # filled by fill_time_values


def fill_time_values(items, now):
    for it in items:
        v = it["values"]
        v[core.field_key("special", "Date (YYYY-MM-DD)")] = now.strftime("%Y-%m-%d")
        v[core.field_key("special", "Date (YYYYMMDD)")] = now.strftime("%Y%m%d")
        v[core.field_key("special", "Time (HHMM)")] = now.strftime("%H%M")


def _type_key(el):
    try:
        return eid_int(el.GetTypeId())
    except Exception:
        return -1


def collect(doc, mode="sheets"):
    """Return (items, catalog, project).

    items   : list of dicts, natural-sorted by number (sheets) or type/name (views)
    catalog : sorted list of (source, parameter name) available for naming
    Parameter values are not read here (LazyValues reads them on demand).
    """
    project = project_info(doc)
    catalog = set()
    shared = {}
    try:
        _param_names(doc.ProjectInformation, "project", catalog)
    except Exception:
        pass
    for sf in SPECIAL_FIELDS:
        catalog.add(("special", sf))

    items = []
    if mode == "sheets":
        tb_map = _title_blocks_by_sheet(doc)
        sampled_tb_types = set()
        sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
        sampled_sheet = False
        for sh in sheets:
            try:
                if sh.IsPlaceholder or sh.IsTemplate:
                    continue
            except Exception:
                continue
            if not sampled_sheet:                       # all sheets share one parameter set
                _param_names(sh, "sheet", catalog)
                sampled_sheet = True
            sid = _remember(sh.Id)
            tb = tb_map.get(sid)
            size, orient = u"", u""
            if tb is not None:
                tkey = _type_key(tb)
                if tkey not in sampled_tb_types:        # one sample per title block type
                    sampled_tb_types.add(tkey)
                    _param_names(tb, "titleblock", catalog)
                try:
                    w = tb.get_Parameter(DB.BuiltInParameter.SHEET_WIDTH).AsDouble() * FEET_TO_MM
                    h = tb.get_Parameter(DB.BuiltInParameter.SHEET_HEIGHT).AsDouble() * FEET_TO_MM
                    size, orient = core.detect_paper(w, h)
                except Exception:
                    pass
            number = core.to_text(sh.SheetNumber)
            name = core.to_text(sh.Name)
            values = LazyValues(doc, {"sheet": sh, "titleblock": tb}, shared)
            values[core.field_key("sheet", "Sheet Number")] = number
            values[core.field_key("sheet", "Sheet Name")] = name
            _special_values(values, project)
            items.append({
                "id": sid, "uid": core.to_text(sh.UniqueId), "kind": "sheet",
                "number": number, "name": name,
                "revision": bip_text(doc, sh, "SHEET_CURRENT_REVISION"),
                "issue_date": bip_text(doc, sh, "SHEET_ISSUE_DATE"),
                "size": size, "orientation": orient, "view_type": u"Sheet",
                "values": values,
            })
        catalog.add(("sheet", "Sheet Number"))
        catalog.add(("sheet", "Sheet Name"))
        items.sort(key=lambda it: core.natural_key(it["number"]))
    else:
        sampled_types = set()
        views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
        for v in views:
            try:
                if v.IsTemplate or isinstance(v, DB.ViewSheet):
                    continue
                vtype = core.to_text(v.ViewType)
                if vtype in SKIP_VIEW_TYPES:
                    continue
                if not v.CanBePrinted:
                    continue
            except Exception:
                continue
            if vtype not in sampled_types:              # one sample per view type
                sampled_types.add(vtype)
                _param_names(v, "view", catalog)
            name = el_name(v)
            values = LazyValues(doc, {"view": v}, shared)
            values[core.field_key("view", "View Name")] = name
            _special_values(values, project)
            items.append({
                "id": _remember(v.Id), "uid": core.to_text(v.UniqueId), "kind": "view",
                "number": u"", "name": name, "revision": u"", "issue_date": u"",
                "size": u"", "orientation": u"", "view_type": vtype,
                "values": values,
            })
        catalog.add(("view", "View Name"))
        items.sort(key=lambda it: (core.natural_key(it["view_type"]), core.natural_key(it["name"])))
    order = {"sheet": 0, "titleblock": 1, "view": 0, "project": 2, "special": 3}
    cat = sorted(catalog, key=lambda sn: (order.get(sn[0], 9), core.natural_key(sn[1])))
    return items, cat, project


def sheet_sets(doc):
    """{set name: set(element id ints)} from Revit's own View/Sheet Sets."""
    out = {}
    try:
        for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet).ToElements():
            ids = set()
            try:
                for v in vs.Views:
                    ids.add(eid_int(v.Id))
            except Exception:
                pass
            out[el_name(vs)] = ids
    except Exception:
        pass
    return out


def browser_selection(uidoc):
    try:
        return set(eid_int(i) for i in uidoc.Selection.GetElementIds())
    except Exception:
        return set()


def open_view_ids(uidoc):
    try:
        return set(eid_int(uv.ViewId) for uv in uidoc.GetOpenUIViews())
    except Exception:
        return set()


def dwg_setups(doc):
    """Ordered list of DWG export setup names (Revit 'Modify DWG/DXF Export Setup')."""
    names = []
    try:
        for s in DB.FilteredElementCollector(doc).OfClass(DB.ExportDWGSettings).ToElements():
            n = el_name(s)
            if n and n not in names:
                names.append(n)
    except Exception:
        pass
    names.sort(key=core.natural_key)
    return [DWG_DEFAULT_SETUP] + names


def paper_formats():
    """Names of DB.ExportPaperFormat members (PDF paper size list)."""
    try:
        from System import Enum
        names = [core.to_text(n) for n in Enum.GetNames(DB.ExportPaperFormat)]
    except Exception:
        names = []
    names = [n for n in names if n != core.PDF_PAPER_DEFAULT]
    return [core.PDF_PAPER_DEFAULT] + names


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
def _set(obj, prop, value, log=None):
    try:
        setattr(obj, prop, value)
        return True
    except Exception as ex:
        if log is not None:
            log.append(u"Option '%s' not applied: %s" % (prop, ex))
        return False


def _enum(enum_type, member, fallback=None):
    et = getattr(DB, enum_type, None)
    if et is None:
        return None
    val = getattr(et, member, None)
    if val is None and fallback:
        val = getattr(et, fallback, None)
    return val


def _set_enum(obj, prop, enum_type, member, log, fallback=None):
    val = _enum(enum_type, member, fallback)
    if val is None:
        log.append(u"Option '%s' value '%s' is not available in this Revit version." % (prop, member))
        return False
    return _set(obj, prop, val, log)


def build_pdf_options(pdf, log):
    o = DB.PDFExportOptions()
    _set(o, "Combine", True, log)
    _set(o, "StopOnError", False, log)
    _set_enum(o, "PaperFormat", "ExportPaperFormat", pdf["paper"], log, core.PDF_PAPER_DEFAULT)
    _set_enum(o, "PaperOrientation", "PageOrientationType", pdf["orientation"], log, "Auto")
    _set_enum(o, "PaperPlacement", "PaperPlacementType", pdf["placement"], log, "Center")
    if pdf["placement"] == "LowerLeft":
        _set(o, "OriginOffsetX", float(pdf["offset_x_mm"]) / FEET_TO_MM, log)   # API uses feet
        _set(o, "OriginOffsetY", float(pdf["offset_y_mm"]) / FEET_TO_MM, log)
    if pdf["zoom_fit"]:
        _set_enum(o, "ZoomType", "ZoomType", "FitToPage", log)
    else:
        _set_enum(o, "ZoomType", "ZoomType", "Zoom", log)
        _set(o, "ZoomPercentage", int(pdf["zoom_percent"]), log)
    _set(o, "AlwaysUseRaster", bool(pdf["raster_processing"]), log)
    _set_enum(o, "ColorDepth", "ColorDepthType", pdf["color"], log, "Color")
    _set_enum(o, "RasterQuality", "RasterQualityType", pdf["raster_quality"], log, "High")
    _set_enum(o, "ExportQuality", "PDFExportQualityType", pdf["dpi"], log, "DPI300")
    _set(o, "ViewLinksInBlue", bool(pdf["view_links_blue"]), log)
    _set(o, "HideReferencePlane", bool(pdf["hide_ref_planes"]), log)
    _set(o, "HideUnreferencedViewTags", bool(pdf["hide_unref_tags"]), log)
    _set(o, "HideScopeBoxes", bool(pdf["hide_scope_boxes"]), log)
    _set(o, "HideCropBoundaries", bool(pdf["hide_crop"]), log)
    _set(o, "ReplaceHalftoneWithThinLines", bool(pdf["halftone_thin"]), log)
    _set(o, "MaskCoincidentLines", bool(pdf["mask_coincident"]), log)
    return o


def build_dwg_options(doc, dwg, log):
    opts = None
    setup = dwg.get("setup") or u""
    if setup and setup != DWG_DEFAULT_SETUP:
        try:
            for s in DB.FilteredElementCollector(doc).OfClass(DB.ExportDWGSettings).ToElements():
                if el_name(s) == setup:
                    opts = s.GetDWGExportOptions()
                    break
        except Exception as ex:
            log.append(u"Could not read DWG setup '%s': %s" % (setup, ex))
        if opts is None:
            log.append(u"DWG setup '%s' was not found in this model; the default setup was used." % setup)
    if opts is None:
        opts = DB.DWGExportOptions()
    _set(opts, "MergedViews", bool(dwg.get("merged", True)), log)
    return opts


def _sheet_number_naming_rule(opts):
    """PDF naming rule = Sheet Number only (so batch files can be matched back)."""
    data = DB.TableCellCombinedParameterData.Create()
    data.CategoryId = DB.ElementId(DB.BuiltInCategory.OST_Sheets)
    data.ParamId = DB.ElementId(DB.BuiltInParameter.SHEET_NUMBER)
    rule = List[DB.TableCellCombinedParameterData]()
    rule.Add(data)
    opts.SetNamingRule(rule)


# ---------------------------------------------------------------------------
# View mode preparation (ProSheets "Advanced settings")
# ---------------------------------------------------------------------------
PREP_MODES = [
    ("hide_isolate", "TemporaryHideIsolate"),
    ("reveal_hidden", "RevealHiddenElements"),
    ("reveal_constraints", "RevealConstraints"),
    ("worksharing", "WorksharingDisplay"),
]


def prepare_views(doc, item_ids, prep, log):
    """Turn off temporary view modes on the sheets and every view placed on them."""
    wanted = [(k, m) for k, m in PREP_MODES if prep.get(k)]
    if not wanted:
        return 0
    targets = []
    seen = set()
    for iid in item_ids:
        v = doc.GetElement(make_id(iid))
        if v is None:
            continue
        group = [v]
        try:
            group.extend(doc.GetElement(x) for x in v.GetAllPlacedViews())
        except Exception:
            pass
        for g in group:
            if g is None:
                continue
            k = eid_int(g.Id)
            if k not in seen:
                seen.add(k)
                targets.append(g)
    modes = [getattr(DB.TemporaryViewMode, m, None) for _k, m in wanted]
    modes = [m for m in modes if m is not None]
    todo = []
    for v in targets:                       # only open a transaction if something is on
        for mode in modes:
            try:
                if v.IsInTemporaryViewMode(mode):
                    todo.append((v, mode))
            except Exception:
                pass
    if not todo:
        return 0
    changed = 0
    t = DB.Transaction(doc, "DLC Export - reset temporary view modes")
    try:
        t.Start()
    except Exception as ex:
        log.append(u"Temporary view modes were left as they are (%s)." % ex)
        return 0
    try:
        for v, mode in todo:
            try:
                v.DisableTemporaryViewMode(mode)
                changed += 1
            except Exception:
                pass
        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        log.append(u"Temporary view modes could not be reset (%s)." % ex)
        return 0
    return changed


# ---------------------------------------------------------------------------
# Running jobs
# ---------------------------------------------------------------------------
class NullReporter(object):
    """Progress sink. The progress window implements the same four methods."""

    def begin(self, jobs):
        pass

    def update(self, job):
        pass

    def cancelled(self):
        return False

    def finish(self, jobs):
        pass


def _friendly(ex):
    msg = core.to_text(getattr(ex, "Message", None) or ex)
    low = msg.lower()
    if "inaccessible" in low or "being used" in low or "opened" in low or "access" in low:
        return u"The file is open in another program (close it in Acrobat/AutoCAD) or the folder is read-only. (%s)" % msg
    if "folder does not exist" in low or "directory" in low:
        return u"The export folder could not be created. Check the path and your permissions. (%s)" % msg
    if "not printable" in low or "exportable" in low:
        return u"Revit says this sheet/view cannot be exported (empty or not printable). (%s)" % msg
    return msg


def _ensure_folder(folder):
    if not os.path.isdir(folder):
        os.makedirs(folder)


def _remove_existing(path):
    if os.path.isdir(path):
        raise IOError(u"a folder with the same name as the file exists: %s" % path)
    if os.path.isfile(path):
        os.remove(path)


def _prepare_destination(job):
    """Create the folder and clear an existing file (overwrite policy). False = job failed."""
    try:
        _ensure_folder(job.folder)
    except Exception as ex:
        job.status = "failed"
        job.message = u"Cannot create folder '%s': %s" % (job.folder, ex)
        return False
    try:
        _remove_existing(job.path)
    except Exception as ex:
        job.status = "failed"
        if os.path.isdir(job.path):
            job.message = (u"A folder with the same name as this file exists in the export "
                           u"folder - rename or remove it. (%s)" % job.path)
        else:
            job.message = (u"Could not overwrite the existing file - it is probably open in "
                           u"another program (Acrobat, AutoCAD). Close it and export again. (%s)" % ex)
        return False
    return True


def make_stage_root(settings):
    """Local temp folder for this run, or None when staging is off."""
    if not settings["output"].get("staging", True):
        return None
    base = os.path.join(tempfile.gettempdir(), u"DLC_Export")
    if not os.path.isdir(base):
        os.makedirs(base)
    return tempfile.mkdtemp(prefix=u"run_", dir=base)


def _new_stage(stage_root, dest_folder):
    if stage_root:
        return tempfile.mkdtemp(prefix=u"s", dir=stage_root)
    _ensure_folder(dest_folder)                        # staging off: hidden folder at destination
    return tempfile.mkdtemp(prefix=u"~dlc_", dir=dest_folder)


def _files(folder, ext):
    try:
        return [f for f in os.listdir(folder) if f.lower().endswith(ext)]
    except Exception:
        return []


def _move(src, dst):
    if os.path.isfile(dst):
        os.remove(dst)
    shutil.move(src, dst)


def _deliver(job, stage, main_file, keep_pcp, move_extras):
    """Move the produced file (and DWG xrefs / .pcp) from the stage to the destination."""
    try:
        _move(os.path.join(stage, main_file), job.path)
    except Exception as ex:
        job.status = "failed"
        job.message = (u"Exported, but the file could not be moved to '%s' - it may be open "
                       u"in another program. (%s)" % (job.folder, ex))
        return False
    main_stem = main_file.rsplit(u".", 1)[0]
    extras = []
    if job.fmt == "dwg":
        if move_extras:
            extras.extend(f for f in _files(stage, u".dwg"))
        if keep_pcp:
            extras.extend(f for f in _files(stage, u".pcp")
                          if move_extras or f.rsplit(u".", 1)[0] == main_stem)
    for f in extras:
        src = os.path.join(stage, f)
        if not os.path.isfile(src):
            continue
        if f.rsplit(u".", 1)[0] == main_stem and f.lower().endswith(u".pcp"):
            dst = ntpath.join(job.folder, job.name + u".pcp")
        else:
            dst = ntpath.join(job.folder, f)
        try:
            _move(src, dst)
        except Exception:
            job.warnings.append(u"Could not move '%s'." % f)
    job.status = "ok"
    return True


def _pick_main(files, job):
    """The file Revit produced for this job in a single-job stage."""
    expected = (job.name + job.ext).lower()
    for f in files:
        if f.lower() == expected:
            return f
    if len(files) == 1:
        return files[0]
    stem = job.name.lower()[:max(1, len(job.name) // 2)]
    starts = sorted((f for f in files if f.lower().startswith(stem)), key=len)
    if starts:
        return starts[0]
    return sorted(files, key=len)[0] if files else None


def run_job(doc, job, pdf_opts, dwg_opts, settings, stage_root=None):
    """Export one job on its own; never raises. Sets job.status/message."""
    if not _prepare_destination(job):
        return job
    try:
        stage = _new_stage(stage_root, job.folder)
    except Exception as ex:
        job.status = "failed"
        job.message = u"Cannot create a temporary export folder: %s" % ex
        return job
    t0 = time.time()
    try:
        try:
            ids = List[DB.ElementId]()
            for i in job.item_ids:
                ids.Add(make_id(i))
            if job.fmt in ("pdf", "pdf_combined"):
                pdf_opts.Combine = True
                pdf_opts.FileName = job.name
                ok = doc.Export(stage, ids, pdf_opts)
            else:
                ok = doc.Export(stage, job.name, ids, dwg_opts)
        except Exception as ex:
            job.status = "failed"
            job.message = _friendly(ex)
            return job
        produced = _files(stage, job.ext.lower())
        main = _pick_main(produced, job)
        if main is None:
            job.status = "failed"
            job.message = (u"Revit finished but no file appeared (export returned %s). The sheet may "
                           u"be empty or a view on it failed to export." % ok)
            return job
        keep_pcp = not settings["dwg"].get("delete_pcp", True)
        merged = settings["dwg"].get("merged", True)
        if _deliver(job, stage, main, keep_pcp, move_extras=not merged) and not ok:
            job.warnings.append(u"Revit reported a problem with part of this export; check the file.")
        return job
    finally:
        job.seconds = time.time() - t0
        shutil.rmtree(stage, ignore_errors=True)


def run_batch(doc, group, pdf_opts, dwg_opts, settings, stage_root, log):
    """Export several sheets in one Revit call; returns how many jobs it finished.

    Jobs it could not match with certainty keep status 'running' and are
    re-exported one by one by the caller.
    """
    ready = [j for j in group if _prepare_destination(j)]
    if len(ready) < 2:
        return len(group) - len(ready)
    fmt = ready[0].fmt
    try:
        stage = _new_stage(stage_root, ready[0].folder)
    except Exception as ex:
        log.append(u"Batch export skipped (temporary folder): %s" % ex)
        return len(group) - len(ready)
    t0 = time.time()
    try:
        ids = List[DB.ElementId]()
        for j in ready:
            ids.Add(make_id(j.item_ids[0]))
        try:
            if fmt == "pdf":
                pdf_opts.Combine = False
                _sheet_number_naming_rule(pdf_opts)
                doc.Export(stage, ids, pdf_opts)
            else:
                doc.Export(stage, core.BATCH_PREFIX, ids, dwg_opts)
        except Exception as ex:
            log.append(u"A batch of %d %s files was re-exported one by one (%s)."
                       % (len(ready), fmt.upper(), _friendly(ex)))
            return len(group) - len(ready)
        finally:
            if fmt == "pdf":
                _set(pdf_opts, "Combine", True)
        files = _files(stage, ready[0].ext.lower())
        mapping = core.match_files(files, ready)
        per_file = (time.time() - t0) / max(1, len(ready))
        keep_pcp = not settings["dwg"].get("delete_pcp", True)
        done = len(group) - len(ready)
        for f, job in mapping.items():
            _deliver(job, stage, f, keep_pcp, move_extras=False)
            job.seconds = per_file
            done += 1
        return done
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _groups(pending, settings):
    """Consecutive batchable jobs of one format, chunked by batch_size; others alone."""
    size = int(settings["output"].get("batch_size", 10) or 1)
    merged = settings["dwg"].get("merged", True)

    def batchable(j):
        if size < 2 or j.kind != "sheet" or not core._norm(j.number):
            return False
        return j.fmt == "pdf" or (j.fmt == "dwg" and merged)

    out = []
    cur = []
    for j in pending:
        if batchable(j) and cur and cur[0].fmt == j.fmt and len(cur) < size:
            cur.append(j)
            continue
        if cur:
            out.append(cur)
        cur = [j] if batchable(j) else []
        if not batchable(j):
            out.append([j])
    if cur:
        out.append(cur)
    return out


def run_jobs(doc, jobs, settings, reporter=None, log=None):
    """Run every pending job in order, batching where possible."""
    reporter = reporter or NullReporter()
    log = [] if log is None else log
    pdf_opts = None
    dwg_opts = None
    if any(j.fmt.startswith("pdf") for j in jobs):
        pdf_opts = build_pdf_options(settings["pdf"], log)
    if any(j.fmt == "dwg" for j in jobs):
        dwg_opts = build_dwg_options(doc, settings["dwg"], log)
    pending = [j for j in jobs if j.status == "pending"]
    try:
        reporter.begin(jobs)
    except Exception:
        pass
    try:
        stage_root = make_stage_root(settings)
    except Exception as ex:
        stage_root = None
        log.append(u"Local staging folder unavailable, exporting directly (%s)." % ex)
    batching = {"pdf": True, "dwg": True}

    def say(job):
        try:
            reporter.update(job)
        except Exception:
            pass

    user_stop = [False]

    def stop_requested():
        try:
            if reporter.cancelled():
                user_stop[0] = True
        except Exception:
            pass
        return user_stop[0]

    try:
        _run_groups(doc, pending, settings, pdf_opts, dwg_opts, stage_root, log,
                    batching, say, stop_requested)
    except Exception as ex:
        log.append(u"The export stopped on an unexpected error: %s" % _friendly(ex))
    finally:
        for j in jobs:
            if j.status in ("pending", "running"):
                j.status = "cancelled"
                j.message = (u"Cancelled by user." if user_stop[0] else
                             u"Not exported: the export stopped on an unexpected error (see notes).")
                say(j)
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)
        try:
            reporter.finish(jobs)
        except Exception:
            pass
    return jobs


def _run_groups(doc, pending, settings, pdf_opts, dwg_opts, stage_root, log, batching,
                say, stop_requested):
    for group in _groups(pending, settings):
        if stop_requested():
            break
        for j in group:
            j.status = "running"
            say(j)
        if len(group) > 1 and batching.get(group[0].fmt):
            finished = run_batch(doc, group, pdf_opts, dwg_opts, settings, stage_root, log)
            if finished == 0:
                batching[group[0].fmt] = False
                log.append(u"Revit's %s batch file names could not be matched; the rest of "
                           u"the %s files were exported one by one." % (group[0].fmt.upper(),
                                                                      group[0].fmt.upper()))
            for j in group:
                if j.status != "running":
                    say(j)
        for j in group:
            if j.status != "running":
                continue
            if stop_requested():
                break
            run_job(doc, j, pdf_opts, dwg_opts, settings, stage_root)
            say(j)

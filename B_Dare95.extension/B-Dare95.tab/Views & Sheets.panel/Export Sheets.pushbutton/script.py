# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Exports any number of sheets or views to PDF and DWG in one run.
File names are built from fields you pick in order (sheet, title block or Project Information parameters, or your own text), each with its own separator, or typed per row.
PDFs can be one per sheet, one combined file, or one combined file per value of a parameter.
Settings, file name fields, ticked sheets and typed names can be saved as profiles.
Read-only: nothing in the model changes.
__________________________________________________
How-to:

-> Click on the button
-> Middle: pick Sheets or Views, search or filter by a View/Sheet Set, and tick what to export
   (select rows with Shift / Ctrl and press Space to tick many at once)
-> Left: add the file name fields in order and set the separator after each one
   (double-click a name in the table to type your own)
-> Right: tick PDF and/or DWG, check their settings, choose the folder
-> Click Export
__________________________________________________
Author: Mohamed Bedair"""

__author__ = "Mohamed Bedair"
# The window stays open after the script returns (modeless), so its engine
# must stay alive too.
__persistentengine__ = True

import datetime
import os
import re
import shutil
import sys
import time

import clr
clr.AddReference("System")
clr.AddReference("System.Data")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System
from System import Environment, TimeSpan
from System.IO import File, FileMode, FileAccess, FileShare
from System.Windows.Threading import DispatcherTimer
from System.Collections.Generic import List
from System.ComponentModel import CancelEventHandler
from System.Data import DataTable, DataColumnChangeEventHandler
from System.Windows import RoutedEventHandler, Visibility, Thickness, TextTrimming
from System.Windows.Controls import (TextBox, TextBlock, DockPanel, Dock,
                                     TextChangedEventHandler,
                                     SelectionChangedEventHandler)
from System.Windows.Input import Key, KeyEventHandler, MouseButtonEventHandler
from System.Windows.Media import FontFamily

from Autodesk.Revit import DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

from pyrevit import forms, script
from pyrevit.coreutils import envvars
import bd_core as bd
from bd_combo_search import enable_combo_search

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import export_core as core      # noqa: E402

uiapp = __revit__               # noqa: F821
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document

TITLE = u"Export Sheets"
STR_T = clr.GetClrType(System.String)
BOOL_T = clr.GetClrType(System.Boolean)

NO_SET = u"All sheets / views (no set filter)"
NO_PROFILE = u"(no profile)"
NO_SETUP = u"(Revit default settings)"
NO_GROUP = u"(choose a parameter)"
DEFAULT_SEP = u" - "            # put between two fields when one is added

# Keeps the open window, its handler and ExternalEvent between button clicks
ENV_WINDOW = "BDARE_EXPORTSHEETS_WINDOW"
ENV_HANDLER = "BDARE_EXPORTSHEETS_HANDLER"
ENV_EVENT = "BDARE_EXPORTSHEETS_EVENT"

SKIP_VIEW_TYPES = (DB.ViewType.Internal, DB.ViewType.ProjectBrowser,
                   DB.ViewType.SystemBrowser, DB.ViewType.Undefined,
                   DB.ViewType.DrawingSheet)

VERSION_LABELS = [("Default", u"(as in the setup)"), ("R2018", u"AutoCAD 2018"),
                  ("R2013", u"AutoCAD 2013"), ("R2010", u"AutoCAD 2010"),
                  ("R2007", u"AutoCAD 2007")]
PROGRESS_COLS = ("PdfState", "PdfText", "PdfTip", "DwgState", "DwgText", "DwgTip")
FMT_PREFIX = {"pdf": "Pdf", "dwg": "Dwg"}     # table column prefix per format
GRID_COL = {"pdf": 4, "dwg": 5}             # index of each progress column in the grid
BG_STALL_SECONDS = 15 * 60      # background: give up when no new PDF for this long
BG_GRACE_SECONDS = 20           # background: wait this long after Revit says it's done
COLOR_LABELS = [("Color", u"Color"), ("GrayScale", u"Grayscale"),
                ("BlackLine", u"Black lines")]


# =============================================================================
# READING THE MODEL (read-only)
# =============================================================================
def friendly_type(view):
    """ViewType as words: FloorPlan -> Floor Plan."""
    text = u"{0}".format(view.ViewType)
    return re.sub(r"(?<=[a-z])(?=[A-Z0-9])", u" ", text).replace(u"Three D", u"3D")


def sort_key(*parts):
    """Text sort key with numbers padded, so A2 sorts before A10 in the grid."""
    text = u" | ".join(core.to_text(p).lower() for p in parts)
    return re.sub(r"\d+", lambda m: m.group(0).zfill(10), text)


class Item(object):
    """One sheet or view that can be exported."""

    def __init__(self, el, kind):
        self.el = el
        self.kind = kind                        # "sheets" or "views"
        self.id = bd.eid_int(el.Id)
        self.key = u"{0}".format(self.id)
        self.uid = el.UniqueId
        self.name = bd.element_name(el)
        if kind == "sheets":
            self.number = el.SheetNumber
            self.sort = sort_key(self.number)
        else:
            self.number = friendly_type(el)
            self.sort = sort_key(self.number, self.name)


def collect_items(doc):
    """{"sheets": [Item], "views": [Item]} - printable, non-template only."""
    sheets, views = [], []
    for el in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            if el.IsTemplate:
                continue
            if isinstance(el, DB.ViewSheet):
                if not el.IsPlaceholder:
                    sheets.append(Item(el, "sheets"))
                continue
            if el.ViewType in SKIP_VIEW_TYPES or not el.CanBePrinted:
                continue
            views.append(Item(el, "views"))
        except Exception:
            continue
    sheets.sort(key=lambda i: i.sort)
    views.sort(key=lambda i: i.sort)
    return {"sheets": sheets, "views": views}


def sheet_sets(doc):
    """[(set name, set of element-id strings)] for the View/Sheet Sets in the model."""
    out = []
    for vss in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet):
        try:
            ids = set(u"{0}".format(bd.eid_int(v.Id)) for v in vss.Views)
            out.append((vss.Name, ids))
        except Exception:
            continue
    out.sort(key=lambda s: s[0].lower())
    return out


def cad_setups(doc):
    try:
        return sorted(DB.BaseExportOptions.GetPredefinedSetupNames(doc))
    except Exception:
        return []


def param_text(doc, p):
    """A parameter's value as the text you see in Revit, or None when empty."""
    if p is None:
        return None
    try:
        st = p.StorageType
        if st == DB.StorageType.String:
            return p.AsString()
        text = p.AsValueString()
        if text:
            return text
        if st == DB.StorageType.Integer:
            return u"{0}".format(p.AsInteger())
        if st == DB.StorageType.Double:
            return u"{0:g}".format(p.AsDouble())
        if st == DB.StorageType.ElementId:
            el = doc.GetElement(p.AsElementId())
            return bd.element_name(el, u"") if el is not None else None
    except Exception:
        pass
    return None


def _param_names(el):
    names = set()
    try:
        for p in el.Parameters:
            if p.Definition is not None and p.Definition.Name:
                names.add(p.Definition.Name)
    except Exception:
        pass
    return names


class Resolver(object):
    """Values for file name fields and {Tokens}, for one sheet / view."""

    BUILTINS = [u"Sheet Number", u"Sheet Name", u"View Name", u"View Type",
                u"Current Revision", u"Current Revision Date",
                u"Current Revision Description", u"Project Number",
                u"Project Name", u"Client Name", u"Model Name",
                u"Export Date", u"Export Time"]

    def __init__(self, doc, now=None):
        self.doc = doc
        self.now = now or datetime.datetime.now()
        self.pinfo = doc.ProjectInformation
        self.blocks = {}
        for tb in (DB.FilteredElementCollector(doc)
                   .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                   .WhereElementIsNotElementType()):
            key = bd.eid_int(tb.OwnerViewId)
            if key not in self.blocks:
                self.blocks[key] = tb
        title = doc.Title or u""
        self.model = title[:-4] if title.lower().endswith(u".rvt") else title

    def _bip(self, el, name):
        # getattr: VIEWER_SHEET_NAME doesn't exist in Revit 2024 -> None,
        # and the caller falls back to the parameter called "Sheet Name".
        bip = getattr(DB.BuiltInParameter, name, None)
        if el is None or bip is None:
            return None
        try:
            return param_text(self.doc, el.get_Parameter(bip))
        except Exception:
            return None

    def builtin(self, item, key):
        """Built-in names work in any Revit language. None = not available."""
        sheet = item.kind == "sheets"
        if key == u"sheet number":
            return item.number if sheet else self._bip(item.el, "VIEWER_SHEET_NUMBER")
        if key == u"sheet name":
            if sheet:
                return item.name
            return self._bip(item.el, "VIEWER_SHEET_NAME") or param_text(
                self.doc, item.el.LookupParameter(u"Sheet Name"))
        if key == u"view name":
            return item.name
        if key == u"view type":
            return u"Sheet" if sheet else item.number
        if key == u"current revision":
            return self._bip(item.el, "SHEET_CURRENT_REVISION")
        if key == u"current revision date":
            return self._bip(item.el, "SHEET_CURRENT_REVISION_DATE")
        if key == u"current revision description":
            return self._bip(item.el, "SHEET_CURRENT_REVISION_DESCRIPTION")
        if key == u"project number":
            return self._bip(self.pinfo, "PROJECT_NUMBER")
        if key == u"project name":
            return self._bip(self.pinfo, "PROJECT_NAME")
        if key == u"client name":
            return self._bip(self.pinfo, "CLIENT_NAME")
        if key == u"model name":
            return self.model
        if key == u"export date":
            return self.now.strftime("%Y-%m-%d")
        if key == u"export time":
            return self.now.strftime("%H%M")
        return None

    def field_value(self, item, field):
        """Text of one file name field for this sheet / view."""
        source, name = field["source"], field["name"]
        if source == "text":
            return name
        if source == "builtin":
            return self.builtin(item, name.strip().lower())
        if source == "item":
            el = item.el
        elif source == "titleblock":
            el = self.blocks.get(item.id)
        else:
            el = self.pinfo
        if el is None:
            return None
        return param_text(self.doc, el.LookupParameter(name))

    def value(self, item, token):
        """Value of a {Token} or group-by name: built-in first, then the
        sheet / view, its title block and Project Information."""
        value = self.builtin(item, token.strip().lower())
        if value is not None:
            return value
        for el in (item.el, self.blocks.get(item.id), self.pinfo):
            if el is not None:
                p = el.LookupParameter(token.strip())
                if p is not None:
                    return param_text(self.doc, p)
        return None

    def catalogue(self, items, mode, sample=40):
        """[(source, name)] the File Name pane offers: built-ins, then the
        parameters of the sheets / views (a sample), their title blocks
        (sheets only) and Project Information, each sorted by name."""
        out = [("builtin", n) for n in self.BUILTINS]
        own, blocks = set(), set()
        for item in items[:sample]:
            own |= _param_names(item.el)
            tb = self.blocks.get(item.id)
            if mode == "sheets" and tb is not None:
                blocks |= _param_names(tb)
        project = _param_names(self.pinfo)
        for source, names in (("item", own), ("titleblock", blocks), ("project", project)):
            out.extend((source, n) for n in sorted(names, key=lambda x: x.lower()))
        return out


# =============================================================================
# EXPORTERS (each returns the written file path, or raises with the reason)
# =============================================================================
def _id_list(items):
    ids = List[DB.ElementId]()
    for item in items:
        ids.Add(item.el.Id)
    return ids


def _clear(path):
    """Delete an old file before writing a new one with the same name."""
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            raise Exception(u"the old file is open in another program")


def _check(ok, path):
    if not os.path.exists(path):
        if ok is False:
            raise Exception(u"Revit reported the export as failed")
        raise Exception(u"Revit did not write the file")
    return path


def pdf_options(s):
    o = DB.PDFExportOptions()
    o.PaperFormat = DB.ExportPaperFormat.Default           # size from title block
    if s["pdf_placement"] == "offset":
        o.PaperPlacement = DB.PaperPlacementType.LowerLeft
        o.OriginOffsetX = bd.mm_to_ft(s["pdf_offset_x"])   # API stores feet
        o.OriginOffsetY = bd.mm_to_ft(s["pdf_offset_y"])
    else:
        o.PaperPlacement = DB.PaperPlacementType.Center
    if s["pdf_zoom"] == "zoom":
        o.ZoomType = DB.ZoomType.Zoom
        o.ZoomPercentage = int(s["pdf_zoom_pct"])
    else:
        o.ZoomType = DB.ZoomType.FitToPage
    o.AlwaysUseRaster = bool(s["pdf_raster"])
    o.RasterQuality = getattr(DB.RasterQualityType, s["pdf_quality"])
    o.ColorDepth = getattr(DB.ColorDepthType, s["pdf_color"])
    # Export DPI: how finely curves are tessellated and raster areas drawn.
    # Not set before, so Revit used its own default - a big lever on PDF time.
    o.ExportQuality = getattr(DB.PDFExportQualityType, "DPI{0}".format(s["pdf_dpi"]))
    o.ViewLinksInBlue = bool(s["pdf_links_blue"])
    o.HideReferencePlane = bool(s["pdf_hide_ref"])
    o.HideUnreferencedViewTags = bool(s["pdf_hide_tags"])
    o.HideScopeBoxes = bool(s["pdf_hide_scope"])
    o.HideCropBoundaries = bool(s["pdf_hide_crop"])
    o.ReplaceHalftoneWithThinLines = bool(s["pdf_halftone"])
    o.MaskCoincidentLines = bool(s["pdf_mask"])
    o.StopOnError = False
    o.Combine = True                # one call = one file with exactly our name
    return o


def _dispose(obj):
    try:
        obj.Dispose()
    except Exception:
        pass


def export_pdf(doc, folder, name, items, s):
    """One PDF. Fresh options every call and disposed after it, so nothing
    from the previous export is carried into this one."""
    path = os.path.join(folder, name + u".pdf")
    _clear(path)
    opts = pdf_options(s)
    try:
        opts.FileName = name
        return _check(doc.Export(folder, _id_list(items), opts), path)
    finally:
        _dispose(opts)


def dwg_options(doc, s):
    """DWG options from the chosen setup, then the window's overrides."""
    opts = None
    if s["cad_setup"]:
        try:
            opts = DB.DWGExportOptions.GetPredefinedOptions(doc, s["cad_setup"])
        except Exception:
            opts = None
    if opts is None:
        opts = DB.DWGExportOptions()
    if s["cad_version"] != "Default":
        opts.FileVersion = getattr(DB.ACADVersion, s["cad_version"])
    opts.SharedCoords = bool(s["cad_shared"])
    opts.MergedViews = bool(s["cad_merged"])
    return opts


def export_dwg(doc, folder, name, item, s):
    path = os.path.join(folder, name + u".dwg")
    _clear(path)
    opts = dwg_options(doc, s)
    try:
        result = _check(doc.Export(folder, name, _id_list([item]), opts), path)
    finally:
        _dispose(opts)
    if s["cad_delete_pcp"]:
        pcp = os.path.join(folder, name + u".pcp")
        if os.path.exists(pcp):
            try:
                os.remove(pcp)
            except Exception:
                pass
    return result


def friendly_error(ex):
    text = u"{0}".format(ex).strip().splitlines()
    return text[0] if text else u"unknown error"


# =============================================================================
# BACKGROUND PDF (Revit 2025+, optional checkbox)
# =============================================================================
# Revit writes "<Sheet Number>.pdf" into a local temp folder; each file is
# then matched to its sheet, renamed to the File Name pane's name and moved
# to the real folder. Sheets only: sheet numbers are unique, view names not.
def background_supported():
    return hasattr(DB.PDFExportOptions, "SetExportInBackground")


def sheet_number_rule():
    rule = DB.TableCellCombinedParameterData.Create()
    rule.CategoryId = DB.ElementId(DB.BuiltInCategory.OST_Sheets)
    rule.ParamId = DB.ElementId(DB.BuiltInParameter.SHEET_NUMBER)
    rule.Prefix = u""
    rule.Suffix = u""
    rule.Separator = u""
    rules = List[DB.TableCellCombinedParameterData]()
    rules.Add(rule)
    return rules


def batch_pdf_options(s, background=False):
    o = pdf_options(s)
    o.Combine = False                       # one file per sheet...
    o.SetNamingRule(sheet_number_rule())    # ...named by its sheet number
    if background:
        o.SetExportInBackground(True)
    return o


def file_ready(path):
    """True when nothing else (Revit's PDF writer) still has the file open."""
    try:
        File.Open(path, FileMode.Open, FileAccess.Read, getattr(FileShare, "None")).Close()
        return True
    except Exception:
        return False


def move_into(src, target):
    """Move a finished PDF from the temp folder to its real name and folder."""
    dst = os.path.join(target["folder"], target["name"] + u".pdf")
    _clear(dst)
    shutil.move(src, dst)
    return dst


def _stage_pdfs(stage):
    try:
        return [f for f in os.listdir(stage) if f.lower().endswith(u".pdf")]
    except Exception:
        return []


def start_background_pdf(doc, stage, targets, s):
    """Hand all these sheets to Revit's background PDF process. Returns at once;
    a BackgroundCollector picks the files up as they arrive."""
    ids = List[DB.ElementId]()
    for t in targets:
        ids.Add(t["item"].el.Id)
    opts = batch_pdf_options(s, background=True)
    try:
        doc.Export(stage, ids, opts)
    finally:
        _dispose(opts)


class BackgroundCollector(object):
    """Watches the temp folder once a second while Revit's background process
    writes the PDFs. A file is taken when its size stopped changing and nothing
    has it open; it is matched to its sheet, renamed and moved, and the window
    is told (on_file). on_done is called once at the end."""

    def __init__(self, app, stage, targets, on_file, on_done, on_tick=None):
        self.app = app
        self.stage = stage
        self.pending = dict((t["key"], t) for t in targets)
        self.on_file = on_file
        self.on_done = on_done
        self.on_tick = on_tick              # (pending keys, seconds since last arrival)
        self.sizes = {}
        self.last = time.time()             # last arrival (or the start)
        self.exported_at = None             # when Revit said the export ended
        self.done = False
        self.aborted = False
        self._handler = None
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(1)
        self.timer.Tick += System.EventHandler(self._tick)

    def start(self):
        try:
            # ONE delegate object, so -= later removes exactly this handler
            from Autodesk.Revit.DB.Events import FileExportedEventArgs
            self._handler = System.EventHandler[FileExportedEventArgs](self._on_exported)
            self.app.FileExported += self._handler      # Revit 2025+: BackgroundOperation
        except Exception:
            self._handler = None
        self.timer.Start()

    def _on_exported(self, sender, args):
        try:
            if not self.done and getattr(args, "BackgroundOperation", False):
                self.exported_at = time.time()
        except Exception:
            pass

    def _tick(self, sender, args):
        try:
            self._poll()
        except Exception as ex:
            self.finish(u"collecting stopped: {0}".format(friendly_error(ex)))

    def _poll(self):
        if self.done:
            return
        for f in _stage_pdfs(self.stage):
            path = os.path.join(self.stage, f)
            try:
                size = os.path.getsize(path)
            except Exception:
                continue
            before = self.sizes.get(f)
            self.sizes[f] = size
            if size == 0 or before != size or not file_ready(path):
                continue                    # still being written
            key = core.match_file(os.path.splitext(f)[0], list(self.pending))
            if key is None:
                continue
            t = self.pending.pop(key)
            now = time.time()
            seconds, self.last = now - self.last, now
            try:
                move_into(path, t)
                self.on_file(t, True, u"", seconds)
            except Exception as ex:
                self.on_file(t, False, friendly_error(ex), seconds)
        if not self.pending:
            return self.finish()
        quiet = time.time() - self.last
        if self.on_tick is not None:
            self.on_tick(self.pending, quiet)
        if self.exported_at is not None and time.time() - self.exported_at > BG_GRACE_SECONDS \
                and quiet > BG_GRACE_SECONDS:
            return self.finish(u"Revit's background export ended without this sheet")
        if quiet > BG_STALL_SECONDS:
            return self.finish(u"no PDF arrived for {0} minutes".format(BG_STALL_SECONDS // 60))

    def finish(self, reason=None):
        if self.done:
            return
        self.done = True
        self.timer.Stop()
        if self._handler is not None:
            try:
                self.app.FileExported -= self._handler
            except Exception:
                pass                        # harmless: the handler checks self.done
        for t in list(self.pending.values()):
            self.on_file(t, False, reason or u"not written", None)
        self.pending.clear()
        self.on_done()

    def abort(self):
        self.aborted = True
        self.finish(u"stopped - Revit may still write it in the temp folder")


def say(message, sub=None):
    """Message box usable from the modeless window (Revit's TaskDialog needs
    an API context; pyRevit's WPF alert doesn't)."""
    forms.alert(message, title=TITLE, sub_msg=sub, warn_icon=False)


def ask_yes_no(message, sub=None):
    return bool(forms.alert(message, title=TITLE, sub_msg=sub, yes=True, no=True,
                            ok=False, warn_icon=False))


class ExportHandler(IExternalEventHandler):
    """Runs ONE export step per Raise().

    Why one file per event: when every export ran inside one long Revit
    command, each PDF took ~3 minutes longer than the one before (MLL300:
    1:48 alone, 18:26 as 8th in a run). Ending the event after each file lets
    Revit go back to idle and clean up before the next one, the way ProSheets
    drives its exports through an ExternalEvent.
    """

    def __init__(self):
        self.step = None            # callable(uiapp) set by the window

    def Execute(self, uiapp):
        step = self.step
        if step is None:
            return
        try:
            step(uiapp)
        except Exception as ex:
            try:
                bd.alert(u"Export step failed: {0}".format(friendly_error(ex)), TITLE)
            except Exception:
                pass

    def GetName(self):
        return "B_Dare95 Export Sheets"


# =============================================================================
# WINDOW
# =============================================================================
class ExportWindow(object):

    def __init__(self, doc, items, store, handler, ext_event):
        self.handler = handler          # runs one export per ExternalEvent
        self.ext_event = ext_event
        self.run = None                 # state of the export in progress
        self.doc = doc
        self.items = items
        self.store = store
        self.resolver = Resolver(doc)
        self.by_key = {"sheets": dict((i.key, i) for i in items["sheets"]),
                       "views": dict((i.key, i) for i in items["views"])}
        self.sets = sheet_sets(doc)
        self.setups = cad_setups(doc)
        self.catalog = {"sheets": self.resolver.catalogue(items["sheets"], "sheets"),
                        "views": self.resolver.catalogue(items["views"], "views")}
        names = []
        for _, name in self.catalog["sheets"] + self.catalog["views"]:
            if name not in names:
                names.append(name)
        self.group_names = names            # for "one PDF per value of ..."
        self.params_shown = []              # (source, name) behind each LstParams row

        self.suppress = [False]             # True while code (not the user) edits things
        self.running = [False]
        self.stop = [False]

        self.w = bd.load_window(__file__)
        self.f = self.w.FindName
        self.sub_brush = self.w.FindResource("SubtextBrush")
        self.accent_brush = self.w.FindResource("AccentBrush")
        self._fill_static_lists()

        s = store["last"]
        self.mode = s["mode"]
        if not items[self.mode]:                # e.g. no sheets yet: start on views
            self.mode = "views" if self.mode == "sheets" else "sheets"
        self._load_naming(s)
        self.tables = {"sheets": self._make_table("sheets", s),
                       "views": self._make_table("views", s)}
        self.apply_settings(s, with_items=False)
        self._wire()
        self._show_mode()
        self.f("StatusText").Text = u"{0}   |   {1} and {2} in this model".format(
            self.resolver.model, bd.plural(len(items["sheets"]), u"sheet"),
            bd.plural(len(items["views"]), u"printable view"))

    # ---------------------------------------------------------------- setup
    def _fill_static_lists(self):
        f = self.f
        for name in [NO_SET] + [n for n, _ in self.sets]:
            f("CmbSet").Items.Add(name)
        f("CmbSet").SelectedIndex = 0
        f("CmbGroupBy").Items.Add(NO_GROUP)
        for name in self.group_names:
            f("CmbGroupBy").Items.Add(name)
        for q in core.CHOICES["pdf_quality"]:
            f("CmbQuality").Items.Add(q)
        for _, label in COLOR_LABELS:
            f("CmbColor").Items.Add(label)
        for dpi in core.CHOICES["pdf_dpi"]:
            f("CmbDpi").Items.Add(u"{0}".format(dpi))
        if not background_supported():          # Revit 2024: no background export
            f("BackgroundPanel").Visibility = Visibility.Collapsed
        f("CmbSetup").Items.Add(NO_SETUP)
        for name in self.setups:
            f("CmbSetup").Items.Add(name)
        for _, label in VERSION_LABELS:
            f("CmbVersion").Items.Add(label)
        self._fill_profiles(self.store["current"])

    def _fill_profiles(self, select):
        cmb = self.f("CmbProfile")
        self.suppress[0] = True
        try:
            cmb.Items.Clear()
            cmb.Items.Add(NO_PROFILE)
            for name in sorted(self.store["profiles"], key=lambda n: n.lower()):
                cmb.Items.Add(name)
            cmb.SelectedItem = select if select in self.store["profiles"] else NO_PROFILE
        finally:
            self.suppress[0] = False

    def _load_naming(self, s):
        self.fields = {"sheets": [dict(x) for x in s["fields_sheets"]],
                       "views": [dict(x) for x in s["fields_views"]]}
        self.naming = {"prefix": s["name_prefix"], "suffix": s["name_suffix"],
                       "replace": s["replace_char"], "skip": s["skip_empty"]}

    def _make_table(self, mode, s):
        t = DataTable(mode)
        # PdfState / DwgState: "" | wait | busy | ok | fail  (drive the progress bars)
        # PdfText / DwgText: the label next to the bar; PdfTip / DwgTip: hover text
        for col in ("Id", "Uid", "Number", "Name", "SortKey", "FileName") + PROGRESS_COLS:
            t.Columns.Add(col, STR_T)
        t.Columns.Add("Pick", BOOL_T)
        t.Columns.Add("Custom", BOOL_T)
        picked = set(s["picked_" + mode])
        names = s["names"]
        for item in self.items[mode]:
            row = t.NewRow()
            row["Id"] = item.key
            row["Uid"] = item.uid
            row["Number"] = item.number
            row["Name"] = item.name
            row["SortKey"] = item.sort
            custom = names.get(item.uid)
            row["Custom"] = bool(custom)
            row["FileName"] = custom or self.item_name(item, mode)
            for col in PROGRESS_COLS:
                row[col] = u""
            row["Pick"] = item.uid in picked
            t.Rows.Add(row)
        t.ColumnChanged += DataColumnChangeEventHandler(self.on_cell_changed)
        return t

    def item_name(self, item, mode=None):
        """File name from the File Name pane's fields for one sheet / view."""
        n = self.naming
        return core.build_name(self.fields[mode or self.mode],
                               lambda fld: self.resolver.field_value(item, fld),
                               n["prefix"], n["suffix"], n["skip"], n["replace"])

    def _wire(self):
        f = self.f

        def click(name, fn):
            f(name).Click += RoutedEventHandler(fn)

        def typed(name, fn):
            f(name).TextChanged += TextChangedEventHandler(fn)

        click("TglSheets", lambda s, e: self.switch_mode("sheets"))
        click("TglViews", lambda s, e: self.switch_mode("views"))
        click("TabPdf", lambda s, e: self.show_page("pdf"))
        click("TabCad", lambda s, e: self.show_page("cad"))
        click("BtnTickShown", lambda s, e: self.tick_shown(True))
        click("BtnUntickShown", lambda s, e: self.tick_shown(False))
        click("BtnTickSelected", lambda s, e: self.tick_selected())
        click("BtnResetNames", lambda s, e: self.reset_names())
        click("BtnBrowse", lambda s, e: self.browse())
        click("BtnExport", lambda s, e: self.run_export())
        click("BtnStop", lambda s, e: self.request_stop())
        click("BtnClose", lambda s, e: self.w.Close())
        click("BtnOpenLog", lambda s, e: self.open_log())
        click("BtnSaveProfile", lambda s, e: self.save_profile())
        click("BtnNewProfile", lambda s, e: self.new_profile())
        click("BtnDeleteProfile", lambda s, e: self.delete_profile())
        for rb in ("RbSeparate", "RbCombine", "RbGroup"):
            click(rb, lambda s, e: self.update_pdf_enabled())

        # File Name pane
        click("BtnAddField", lambda s, e: self.add_selected_params())
        click("BtnAddText", lambda s, e: self.add_text())
        click("BtnFieldUp", lambda s, e: self.move_field(-1))
        click("BtnFieldDown", lambda s, e: self.move_field(1))
        click("BtnFieldRemove", lambda s, e: self.remove_field())
        click("ChkSkipEmpty", lambda s, e: self.on_naming_option())
        click("ChkPdf", lambda s, e: self.update_format_columns())
        click("ChkDwg", lambda s, e: self.update_format_columns())
        typed("TxtParamSearch", lambda s, e: self.fill_params())
        typed("TxtCustom", lambda s, e: self._hint("TxtCustom", "CustomHint"))
        typed("TxtSep", lambda s, e: self.on_sep())
        for name in ("TxtPrefix", "TxtSuffix", "TxtReplace"):
            typed(name, lambda s, e: self.on_naming_option())
        f("LstParams").MouseDoubleClick += MouseButtonEventHandler(
            lambda s, e: self.add_selected_params())
        f("LstFields").SelectionChanged += SelectionChangedEventHandler(
            lambda s, e: self.on_field_selected())
        f("TxtCustom").KeyDown += KeyEventHandler(self.on_custom_key)

        typed("TxtSearch", lambda s, e: self.apply_filter())
        f("CmbSet").SelectionChanged += SelectionChangedEventHandler(lambda s, e: self.apply_filter())
        f("CmbProfile").SelectionChanged += SelectionChangedEventHandler(self.on_profile)
        f("Grid").PreviewKeyDown += KeyEventHandler(self.on_grid_key)
        self.w.Closing += CancelEventHandler(self.on_closing)

    def _hint(self, box, hint):
        empty = not (self.f(box).Text or u"")
        self.f(hint).Visibility = Visibility.Visible if empty else Visibility.Collapsed

    # ---------------------------------------------------------------- table
    @property
    def table(self):
        return self.tables[self.mode]

    def switch_mode(self, mode):
        self.f("TglSheets").IsChecked = mode == "sheets"
        self.f("TglViews").IsChecked = mode == "views"
        if mode == self.mode:
            return
        self.f("Grid").CommitEdit()
        self.mode = mode
        self._show_mode()

    def _show_mode(self):
        f = self.f
        f("TglSheets").IsChecked = self.mode == "sheets"
        f("TglViews").IsChecked = self.mode == "views"
        f("Grid").Columns[1].Header = u"Number" if self.mode == "sheets" else u"View type"
        f("Grid").ItemsSource = self.table.DefaultView
        self.fill_params()
        self.fill_fields()
        self.apply_filter()

    def on_cell_changed(self, sender, e):
        if self.suppress[0]:
            return
        col = e.Column.ColumnName
        if col == "FileName":
            self.suppress[0] = True
            try:
                typed = core.to_text(e.Row["FileName"]).strip()
                if typed:
                    e.Row["Custom"] = True
                else:                   # emptied: back to the File Name pane's name
                    item = self.by_key[self.mode].get(e.Row["Id"])
                    if item is not None:
                        e.Row["FileName"] = self.item_name(item)
                    e.Row["Custom"] = False
            finally:
                self.suppress[0] = False
        elif col == "Pick":
            self.update_count()

    def apply_filter(self):
        if self.suppress[0]:
            return
        parts = []
        text = (self.f("TxtSearch").Text or u"").strip()
        self._hint("TxtSearch", "SearchHint")
        if text:
            safe = text.replace(u"'", u"''").replace(u"[", u"[[]").replace(
                u"%", u"[%]").replace(u"*", u"[*]")
            parts.append(u"(Number LIKE '%{0}%' OR Name LIKE '%{0}%' OR FileName LIKE '%{0}%')"
                         .format(safe))
        set_name = self.f("CmbSet").SelectedItem
        if set_name and set_name != NO_SET:
            ids = dict(self.sets).get(set_name, set())
            if ids:
                parts.append(u"Id IN ({0})".format(u",".join(u"'{0}'".format(i) for i in ids)))
            else:
                parts.append(u"Id = '-1'")
        try:
            self.table.DefaultView.RowFilter = u" AND ".join(parts)
        except Exception:
            self.table.DefaultView.RowFilter = u""
        self.update_count()

    def update_count(self):
        total = self.table.Rows.Count
        shown = self.table.DefaultView.Count
        picked = len(self.table.Select("Pick = true"))
        word = u"sheet" if self.mode == "sheets" else u"view"
        text = u"{0} of {1} ticked".format(picked, bd.plural(total, word))
        if shown != total:
            text += u"   ({0} shown)".format(shown)
        self.f("CountText").Text = text

    def _bulk(self, rows, value):
        self.suppress[0] = True
        try:
            for row in rows:
                row["Pick"] = value
        finally:
            self.suppress[0] = False
        self.update_count()

    def tick_shown(self, value):
        self._bulk([rv.Row for rv in self.table.DefaultView], value)

    def tick_selected(self, toggle=False):
        rows = [rv.Row for rv in self.f("Grid").SelectedItems if hasattr(rv, "Row")]
        if not rows:
            return
        value = True
        if toggle:
            value = not all(bool(r["Pick"]) for r in rows)
        self._bulk(rows, value)

    def on_grid_key(self, sender, e):
        if e.Key == Key.Space and not isinstance(e.OriginalSource, TextBox):
            self.tick_selected(toggle=True)
            e.Handled = True

    def reset_names(self):
        self.suppress[0] = True
        try:
            for row in self.table.Rows:
                row["Custom"] = False
        finally:
            self.suppress[0] = False
        self.refresh_names()

    # ---------------------------------------------------------------- file name pane
    def _list_row(self, text, tag, tag_brush=None, mono=False):
        """A list row: text on the left, a grey tag on the right."""
        panel = DockPanel()
        panel.LastChildFill = True
        right = TextBlock()
        right.Text = tag
        right.Foreground = tag_brush or self.sub_brush
        right.FontSize = 11
        right.Margin = Thickness(8, 0, 0, 0)
        DockPanel.SetDock(right, Dock.Right)
        left = TextBlock()
        left.Text = text
        left.TextTrimming = TextTrimming.CharacterEllipsis
        if mono:
            left.FontFamily = FontFamily("Consolas")
        panel.Children.Add(right)
        panel.Children.Add(left)
        return panel

    def fill_params(self):
        """Available parameters for the current mode, filtered by the search box."""
        self._hint("TxtParamSearch", "ParamSearchHint")
        words = (self.f("TxtParamSearch").Text or u"").lower().split()
        lst = self.f("LstParams")
        lst.Items.Clear()
        self.params_shown = []
        for source, name in self.catalog[self.mode]:
            label = core.source_label(source, self.mode)
            hay = (name + u" " + label).lower()
            if all(w in hay for w in words):
                self.params_shown.append((source, name))
                lst.Items.Add(self._list_row(name, label))

    def fill_fields(self, select=None):
        """The fields of the current mode, in order. select: index to highlight."""
        lst = self.f("LstFields")
        fields = self.fields[self.mode]
        self.suppress[0] = True
        try:
            lst.Items.Clear()
            for i, fld in enumerate(fields):
                text = (u'"{0}"'.format(fld["name"]) if fld["source"] == "text"
                        else fld["name"])
                last = i == len(fields) - 1
                sep = u"" if last else u'then "{0}"'.format(fld["sep"])
                tag = u"{0}   {1}".format(core.source_label(fld["source"], self.mode), sep)
                lst.Items.Add(self._list_row(text, tag.strip()))
            if select is not None and 0 <= select < len(fields):
                lst.SelectedIndex = select
        finally:
            self.suppress[0] = False
        self.on_field_selected()

    def _selected_field(self):
        index = self.f("LstFields").SelectedIndex
        fields = self.fields[self.mode]
        return index if 0 <= index < len(fields) else -1

    def on_field_selected(self):
        index = self._selected_field()
        has = index >= 0
        for name in ("BtnFieldUp", "BtnFieldDown", "BtnFieldRemove", "TxtSep"):
            self.f(name).IsEnabled = has
        self.suppress[0] = True
        try:
            self.f("TxtSep").Text = self.fields[self.mode][index]["sep"] if has else u""
        finally:
            self.suppress[0] = False

    def _add_fields(self, new):
        fields = self.fields[self.mode]
        for fld in new:
            if fields and not fields[-1]["sep"]:
                fields[-1]["sep"] = DEFAULT_SEP     # a separator between old and new
            fields.append(fld)
        self.fill_fields(select=len(fields) - 1)
        self.refresh_names()

    def add_selected_params(self):
        lst = self.f("LstParams")
        indexes = sorted(lst.Items.IndexOf(obj) for obj in lst.SelectedItems)
        new = [core.field(self.params_shown[i][0], self.params_shown[i][1])
               for i in indexes if 0 <= i < len(self.params_shown)]
        if new:
            self._add_fields(new)

    def add_text(self):
        text = self.f("TxtCustom").Text or u""
        if not text.strip():
            return
        self._add_fields([core.field("text", text)])
        self.f("TxtCustom").Text = u""

    def on_custom_key(self, sender, e):
        if e.Key == Key.Enter:
            self.add_text()
            e.Handled = True

    def move_field(self, step):
        index = self._selected_field()
        fields = self.fields[self.mode]
        target = index + step
        if index < 0 or not 0 <= target < len(fields):
            return
        fields[index], fields[target] = fields[target], fields[index]
        self.fill_fields(select=target)
        self.refresh_names()

    def remove_field(self):
        index = self._selected_field()
        if index < 0:
            return
        del self.fields[self.mode][index]
        self.fill_fields(select=min(index, len(self.fields[self.mode]) - 1))
        self.refresh_names()

    def on_sep(self):
        if self.suppress[0]:
            return
        index = self._selected_field()
        if index < 0:
            return
        self.fields[self.mode][index]["sep"] = self.f("TxtSep").Text or u""
        self.fill_fields(select=index)
        self.f("TxtSep").CaretIndex = len(self.f("TxtSep").Text or u"")
        self.refresh_names()

    def on_naming_option(self):
        if self.suppress[0]:
            return
        f = self.f
        self.naming = {"prefix": f("TxtPrefix").Text or u"",
                       "suffix": f("TxtSuffix").Text or u"",
                       "replace": core.clean_replace_char(f("TxtReplace").Text),
                       "skip": bool(f("ChkSkipEmpty").IsChecked)}
        self.refresh_names("sheets")
        self.refresh_names("views")

    def refresh_names(self, mode=None):
        """Put the File Name pane's name on every row that wasn't typed by hand."""
        mode = mode or self.mode
        self.suppress[0] = True
        try:
            for row in self.tables[mode].Rows:
                if not row["Custom"]:
                    row["FileName"] = self.item_name(self.by_key[mode][row["Id"]], mode)
        finally:
            self.suppress[0] = False

    # ---------------------------------------------------------------- pages
    def show_page(self, page):
        f = self.f
        for name, key in (("Pdf", "pdf"), ("Cad", "cad")):
            f("Tab" + name).IsChecked = key == page
            f("Page" + name).Visibility = Visibility.Visible if key == page else Visibility.Collapsed

    def update_pdf_enabled(self):
        f = self.f
        f("TxtCombinedName").IsEnabled = bool(f("RbCombine").IsChecked)
        f("CmbGroupBy").IsEnabled = bool(f("RbGroup").IsChecked)
        f("ChkBackground").IsEnabled = bool(f("RbSeparate").IsChecked)


    def browse(self):
        folder = forms.pick_folder(title=u"Folder for the exported files")
        if folder:
            self.f("TxtFolder").Text = folder

    # ---------------------------------------------------------------- settings
    def read_settings(self):
        """Everything on screen as a settings dict (see export_core.DEFAULTS)."""
        f = self.f
        f("Grid").CommitEdit()
        s = core.default_settings()
        s["mode"] = self.mode
        s["fields_sheets"] = [dict(x) for x in self.fields["sheets"]]
        s["fields_views"] = [dict(x) for x in self.fields["views"]]
        s["name_prefix"] = self.naming["prefix"]
        s["name_suffix"] = self.naming["suffix"]
        s["replace_char"] = self.naming["replace"]
        s["skip_empty"] = self.naming["skip"]

        s["formats"] = [fmt for fmt, name in (("pdf", "ChkPdf"), ("dwg", "ChkDwg"))
                        if f(name).IsChecked]
        s["folder"] = (f("TxtFolder").Text or u"").strip()
        s["subfolders"] = bool(f("ChkSubfolders").IsChecked)
        s["overwrite"] = bool(f("ChkOverwrite").IsChecked)
        s["open_folder"] = bool(f("ChkOpenFolder").IsChecked)

        s["pdf_output"] = ("combine" if f("RbCombine").IsChecked else
                           "group" if f("RbGroup").IsChecked else "separate")
        s["pdf_combined_name"] = f("TxtCombinedName").Text or core.PATTERN_COMBINED
        group = f("CmbGroupBy").SelectedItem
        s["pdf_group_by"] = group if group and group != NO_GROUP else u""
        s["pdf_placement"] = "offset" if f("RbOffset").IsChecked else "center"
        s["pdf_offset_x"] = bd.parse_mm(f("TxtOffX").Text, True, 0.0)
        s["pdf_offset_y"] = bd.parse_mm(f("TxtOffY").Text, True, 0.0)
        s["pdf_zoom"] = "zoom" if f("RbZoom").IsChecked else "fit"
        zoom = bd.parse_mm((f("TxtZoom").Text or u"").replace(u"%", u""), False, 100)
        s["pdf_zoom_pct"] = int(zoom) if 10 <= zoom <= 1000 else 100
        s["pdf_raster"] = bool(f("RbRaster").IsChecked)
        s["pdf_quality"] = f("CmbQuality").SelectedItem or "High"
        s["pdf_color"] = COLOR_LABELS[max(0, f("CmbColor").SelectedIndex)][0]
        s["pdf_dpi"] = int(f("CmbDpi").SelectedItem or 300)
        s["pdf_background"] = bool(f("ChkBackground").IsChecked)
        for key, name in self.PDF_CHECKS:
            s[key] = bool(f(name).IsChecked)

        setup = f("CmbSetup").SelectedItem
        s["cad_setup"] = setup if setup and setup != NO_SETUP else u""
        s["cad_version"] = VERSION_LABELS[max(0, f("CmbVersion").SelectedIndex)][0]
        s["cad_merged"] = bool(f("ChkMerged").IsChecked)
        s["cad_shared"] = bool(f("ChkShared").IsChecked)
        s["cad_delete_pcp"] = bool(f("ChkDeletePcp").IsChecked)

        names = {}
        for mode in ("sheets", "views"):
            t = self.tables[mode]
            s["picked_" + mode] = [r["Uid"] for r in t.Select("Pick = true")]
            for r in t.Select("Custom = true"):
                names[r["Uid"]] = r["FileName"]
        s["names"] = names
        return core.clean_settings(s)

    PDF_CHECKS = (("pdf_links_blue", "ChkLinksBlue"), ("pdf_hide_ref", "ChkHideRef"),
                  ("pdf_hide_tags", "ChkHideTags"), ("pdf_hide_scope", "ChkHideScope"),
                  ("pdf_hide_crop", "ChkHideCrop"), ("pdf_halftone", "ChkHalftone"),
                  ("pdf_mask", "ChkMask"))

    def apply_settings(self, s, with_items=True):
        """Put a settings dict on screen. with_items also restores the file
        name fields, ticked rows and typed names (used when a profile is chosen)."""
        f = self.f
        self.suppress[0] = True
        try:
            f("TxtPrefix").Text = s["name_prefix"]
            f("TxtSuffix").Text = s["name_suffix"]
            f("TxtReplace").Text = s["replace_char"]
            f("ChkSkipEmpty").IsChecked = s["skip_empty"]

            f("ChkPdf").IsChecked = "pdf" in s["formats"]
            f("ChkDwg").IsChecked = "dwg" in s["formats"]
            f("TxtFolder").Text = s["folder"] or os.path.join(
                Environment.GetFolderPath(Environment.SpecialFolder.Desktop), u"Revit Export")
            f("ChkSubfolders").IsChecked = s["subfolders"]
            f("ChkOverwrite").IsChecked = s["overwrite"]
            f("ChkOpenFolder").IsChecked = s["open_folder"]

            f("RbSeparate").IsChecked = s["pdf_output"] == "separate"
            f("RbCombine").IsChecked = s["pdf_output"] == "combine"
            f("RbGroup").IsChecked = s["pdf_output"] == "group"
            f("TxtCombinedName").Text = s["pdf_combined_name"]
            f("CmbGroupBy").SelectedItem = (s["pdf_group_by"] if s["pdf_group_by"] in self.group_names
                                            else NO_GROUP)
            f("RbCenter").IsChecked = s["pdf_placement"] == "center"
            f("RbOffset").IsChecked = s["pdf_placement"] == "offset"
            f("TxtOffX").Text = u"{0:g}".format(s["pdf_offset_x"])
            f("TxtOffY").Text = u"{0:g}".format(s["pdf_offset_y"])
            f("RbFit").IsChecked = s["pdf_zoom"] == "fit"
            f("RbZoom").IsChecked = s["pdf_zoom"] == "zoom"
            f("TxtZoom").Text = u"{0}".format(s["pdf_zoom_pct"])
            f("RbVector").IsChecked = not s["pdf_raster"]
            f("RbRaster").IsChecked = s["pdf_raster"]
            f("CmbQuality").SelectedItem = s["pdf_quality"]
            f("CmbColor").SelectedIndex = [k for k, _ in COLOR_LABELS].index(s["pdf_color"])
            f("CmbDpi").SelectedItem = u"{0}".format(s["pdf_dpi"])
            f("ChkBackground").IsChecked = s["pdf_background"]
            for key, name in self.PDF_CHECKS:
                f(name).IsChecked = s[key]

            f("CmbSetup").SelectedItem = s["cad_setup"] if s["cad_setup"] in self.setups else NO_SETUP
            f("CmbVersion").SelectedIndex = [k for k, _ in VERSION_LABELS].index(s["cad_version"])
            f("ChkMerged").IsChecked = s["cad_merged"]
            f("ChkShared").IsChecked = s["cad_shared"]
            f("ChkDeletePcp").IsChecked = s["cad_delete_pcp"]

            if with_items:
                self._load_naming(s)
                for mode in ("sheets", "views"):
                    picked = set(s["picked_" + mode])
                    for row in self.tables[mode].Rows:
                        custom = s["names"].get(row["Uid"])
                        row["Pick"] = row["Uid"] in picked
                        row["Custom"] = bool(custom)
                        if custom:
                            row["FileName"] = custom
        finally:
            self.suppress[0] = False
        self.update_pdf_enabled()
        self.update_format_columns()
        if with_items:
            self.refresh_names("sheets")
            self.refresh_names("views")
            if s["mode"] != self.mode and self.items[s["mode"]]:
                self.mode = s["mode"]
            self._show_mode()

    # ---------------------------------------------------------------- profiles
    def _save_store(self):
        try:
            core.save_store(self.store)
        except Exception as ex:
            self.f("ResultText").Text = u"Settings could not be saved: {0}".format(friendly_error(ex))

    def on_profile(self, sender, e):
        if self.suppress[0]:
            return
        name = self.f("CmbProfile").SelectedItem
        if name and name in self.store["profiles"]:
            self.store["current"] = name
            self.apply_settings(self.store["profiles"][name], with_items=True)
            self.f("ResultText").Text = u"Profile '{0}' loaded.".format(name)
        else:
            self.store["current"] = u""

    def save_profile(self):
        name = self.f("CmbProfile").SelectedItem
        if not name or name == NO_PROFILE:
            return self.new_profile()
        self.store["profiles"][name] = self.read_settings()
        self._save_store()
        self.f("ResultText").Text = u"Profile '{0}' saved.".format(name)

    def new_profile(self):
        name = forms.ask_for_string(
            prompt=u"Profile name. It keeps the formats and their settings, the folder, "
                   u"the file name fields, the ticked sheets / views and typed names.",
            title=TITLE)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.store["profiles"] and not ask_yes_no(
                u"Profile '{0}' already exists".format(name),
                u"Replace it with the current settings?"):
            return
        self.store["profiles"][name] = self.read_settings()
        self.store["current"] = name
        self._save_store()
        self._fill_profiles(name)
        self.f("ResultText").Text = u"Profile '{0}' saved.".format(name)

    def delete_profile(self):
        name = self.f("CmbProfile").SelectedItem
        if not name or name not in self.store["profiles"]:
            return
        if not ask_yes_no(u"Delete the profile '{0}'?".format(name),
                          u"The settings on screen stay as they are."):
            return
        del self.store["profiles"][name]
        self.store["current"] = u""
        self._save_store()
        self._fill_profiles(NO_PROFILE)

    def on_closing(self, sender, e):
        if self.running[0]:
            e.Cancel = True
            self.f("ResultText").Text = u"Export is running - press Stop first."
            return
        try:
            self.store["last"] = self.read_settings()
            self._save_store()
        except Exception:
            pass

    # ---------------------------------------------------------------- export
    def _set_busy(self, busy):
        self.running[0] = busy
        self.f("Body").IsEnabled = not busy
        self.f("ProfileBar").IsEnabled = not busy
        self.f("BtnExport").IsEnabled = not busy
        self.f("BtnClose").IsEnabled = not busy
        self.f("BtnStop").IsEnabled = busy

    def _set_progress(self, rows, fmt, state, text, tip=u""):
        """One format's progress bar on these rows (see PROGRESS_COLS)."""
        p = FMT_PREFIX[fmt]
        self.suppress[0] = True
        try:
            for row in rows:
                row[p + "State"] = state
                row[p + "Text"] = text
                row[p + "Tip"] = tip
        finally:
            self.suppress[0] = False

    def _mark(self, rows, fmt, ok, detail=u"", seconds=None):
        """A finished file: full green bar with its time, or red with the reason."""
        if ok:
            text = core.fmt_seconds(seconds) if seconds is not None else u"done"
            tip = u"{0} written{1}{2}".format(
                core.FORMAT_LABELS[fmt],
                u" in " + text if seconds is not None else u"",
                u" ({0})".format(detail) if detail else u"")
            self._set_progress(rows, fmt, u"ok", text, tip)
        else:
            self._set_progress(rows, fmt, u"fail", u"failed",
                               u"{0} failed: {1}".format(core.FORMAT_LABELS[fmt], detail))

    def _busy(self, rows, fmt, text=u"now"):
        """The file Revit is working on (amber bar)."""
        self._set_progress(rows, fmt, u"busy", text,
                           u"{0} exporting".format(core.FORMAT_LABELS[fmt]))

    def update_format_columns(self):
        """Show the PDF / DWG progress column only for a ticked format."""
        for fmt, chk in (("pdf", "ChkPdf"), ("dwg", "ChkDwg")):
            self.f("Grid").Columns[GRID_COL[fmt]].Visibility = (
                Visibility.Visible if self.f(chk).IsChecked else Visibility.Collapsed)

    def _validate(self, s, rows):
        if not rows:
            return u"Tick at least one sheet or view."
        if not s["formats"]:
            return u"Tick PDF and / or DWG."
        if "pdf" in s["formats"] and s["pdf_output"] == "group" and not s["pdf_group_by"]:
            return u"Choose the parameter to group the PDF files by."
        if not s["folder"]:
            return u"Choose the folder to save to."
        return None

    def pick_engine(self, s, pairs):
        """"background" when the checkbox is on and it can be used, else
        "per_sheet" - plus why, when the checkbox couldn't be honoured."""
        if not s["pdf_background"] or s["pdf_output"] != "separate":
            return "per_sheet", None
        if self.mode != "sheets":
            return "per_sheet", u"Background export is for sheets; views were exported one by one."
        if not background_supported():
            return "per_sheet", u"Revit's background PDF export needs Revit 2025 or newer."
        if core.duplicate_keys([p[1].number for p in pairs]):
            return "per_sheet", u"Some sheet numbers only differ by punctuation, so they were exported one by one."
        return "background", None

    def build_jobs(self, s, rows):
        """Job dicts, in the order they run. kind: "file" (one call, one file)
        or "background" (Revit 2025+ background process, many files).
        files = how many files the job produces. Always run sheet by sheet
        (each sheet's PDF, then its DWG) - see export_core.order_jobs."""
        jobs = []
        taken = set()
        items = [self.by_key[self.mode][r["Id"]] for r in rows]
        pairs = list(zip(rows, items))
        rc = s["replace_char"]

        def name_for(fmt, ext, base):
            folder = core.format_folder(s["folder"], fmt, s["subfolders"])
            return core.unique_name(folder, core.sanitize(base, replace_char=rc), ext,
                                    s["overwrite"], taken)

        def job(fmt, job_rows, name, run, kind="file", files=1):
            single = kind == "file" and len(job_rows) == 1
            jobs.append({"fmt": fmt, "rows": job_rows, "name": name, "run": run,
                         "kind": kind, "files": files,
                         "rows_key": job_rows[0]["Id"] if single else None})

        if "pdf" in s["formats"]:
            folder = core.format_folder(s["folder"], "pdf", s["subfolders"])
            if s["pdf_output"] == "separate":
                engine, note = self.pick_engine(s, pairs)
                self.run_notes = [note] if note else []
                if engine == "per_sheet":
                    for row, item in pairs:
                        name = name_for("pdf", u".pdf", row["FileName"])
                        job("pdf", [row], name,
                            self._job(export_pdf, self.doc, folder, name, [item], s))
                else:
                    targets = [{"key": item.number, "row": row, "item": item, "folder": folder,
                                "name": name_for("pdf", u".pdf", row["FileName"])}
                               for row, item in pairs]
                    job("pdf", rows, u"{0} sheets in Revit's background".format(len(targets)),
                        lambda t=targets: start_background_pdf(self.doc, self.run["stage"], t, s),
                        "background", len(targets))
                    jobs[-1]["targets"] = targets
            elif s["pdf_output"] == "combine":
                base = core.expand(s["pdf_combined_name"],
                                   lambda t: self.resolver.value(items[0], t), u"Combined", rc)
                name = name_for("pdf", u".pdf", base)
                job("pdf", rows, name, self._job(export_pdf, self.doc, folder, name, items, s))
            else:
                groups = core.group_rows(pairs, lambda p: self.resolver.value(p[1], s["pdf_group_by"]))
                for value, members in groups:
                    name = name_for("pdf", u".pdf", value)
                    job("pdf", [m[0] for m in members], name,
                        self._job(export_pdf, self.doc, folder, name, [m[1] for m in members], s))
        if "dwg" in s["formats"]:
            folder = core.format_folder(s["folder"], "dwg", s["subfolders"])
            for row, item in pairs:
                name = name_for("dwg", u".dwg", row["FileName"])
                job("dwg", [row], name, self._job(export_dwg, self.doc, folder, name, item, s))
        return core.order_jobs(jobs, [r["Id"] for r in rows])

    @staticmethod
    def _job(fn, *args):
        return lambda: fn(*args)

    def run_export(self):
        """Check the settings, build the job list and start the first step.
        Each file is then exported in its own ExternalEvent (see ExportHandler)."""
        if self.running[0]:
            return
        s = self.read_settings()
        rows = list(self.table.Select("Pick = true", "SortKey ASC"))
        problem = self._validate(s, rows)
        if problem:
            say(problem)
            return
        if not self.doc.IsValidObject:
            say(u"The model this window was opened for is closed.",
                u"Close this window and open Export Sheets again.")
            return
        for fmt in s["formats"]:
            folder = core.format_folder(s["folder"], fmt, s["subfolders"])
            if not os.path.isdir(folder):
                try:
                    os.makedirs(folder)
                except Exception as ex:
                    say(u"The folder could not be created", u"{0}\n\n{1}".format(
                        folder, friendly_error(ex)))
                    return
        self.store["last"] = s
        self._save_store()

        self.run_notes = []
        try:
            jobs = self.build_jobs(s, rows)
        except Exception as ex:
            say(u"The export settings were not accepted", friendly_error(ex))
            return
        stage = None
        if any(j["kind"] != "file" for j in jobs):
            try:
                core.clean_stages()
                stage = core.new_stage(datetime.datetime.now())
            except Exception as ex:
                say(u"The local temp folder could not be created", friendly_error(ex))
                return

        # every ticked row waits for each chosen format; the rest show a dash
        self.suppress[0] = True
        try:
            for row in self.table.Rows:
                for fmt, p in FMT_PREFIX.items():
                    todo = bool(row["Pick"]) and fmt in s["formats"]
                    row[p + "State"] = u"wait" if todo else u""
                    row[p + "Text"] = u"waiting" if todo else u"–"
                    row[p + "Tip"] = u""
        finally:
            self.suppress[0] = False
        self.update_format_columns()

        total_files = sum(j["files"] for j in jobs)
        bar = self.f("Progress")
        bar.Maximum = max(1, total_files)
        bar.Value = 0
        self.stop[0] = False
        self.run = {"s": s, "jobs": jobs, "index": 0, "done": 0, "failed": 0,
                    "files": total_files, "failures": [], "timings": [],
                    "started": datetime.datetime.now(), "clock": time.time(),
                    "stage": stage, "bg": None, "notes": list(self.run_notes)}
        self._set_busy(True)
        self._show_next()
        self.handler.step = self._export_step
        self.ext_event.Raise()

    def _progress(self):
        r = self.run
        self.f("Progress").Value = r["done"] + r["failed"]

    def _show_next(self):
        """Mark the next job as exporting, so it shows while Revit gets to it."""
        r = self.run
        if r["index"] < len(r["jobs"]):
            j = r["jobs"][r["index"]]
            if j["kind"] == "file":
                self._busy(j["rows"], j["fmt"])
            self.f("ResultText").Text = u"Job {0} of {1}:  {2}  {3}".format(
                r["index"] + 1, len(r["jobs"]), core.FORMAT_LABELS[j["fmt"]], j["name"])

    def _export_step(self, uiapp):
        """ExternalEvent body. Any unexpected error ends the run cleanly
        instead of leaving the window stuck in 'exporting'."""
        try:
            self._export_one()
        except Exception as ex:
            if self.run is not None:
                self.run["failures"].append(u"Export stopped: {0}".format(friendly_error(ex)))
            self._finish()

    def _record(self, fmt, rows, name, ok, reason=u"", seconds=None, count=None, detail=u""):
        """Count one finished file (or a failed one), mark its rows, log it."""
        r = self.run
        label = core.FORMAT_LABELS[fmt]
        if ok:
            r["done"] += 1
        else:
            r["failed"] += 1
            r["failures"].append(u"{0}  {1}:  {2}".format(label, name, reason))
        self._mark(rows, fmt, ok, reason if not ok else detail, seconds)
        if seconds is not None:
            r["timings"].append({"fmt": label, "name": name, "count": count or len(rows),
                                 "seconds": seconds, "ok": ok, "reason": reason})
        self._progress()
        self._write_log(r["s"], r["timings"], time.time() - r["clock"], r["started"])

    def _export_one(self):
        """Run ONE job, then raise the event again for the next one, so Revit
        returns to idle between jobs."""
        r = self.run
        if r is None:
            return
        if self.stop[0] or r["index"] >= len(r["jobs"]):
            return self._end_jobs()
        if not self.doc.IsValidObject:
            r["failures"].append(u"The model was closed - export stopped.")
            return self._end_jobs()

        j = r["jobs"][r["index"]]
        fmt, job_rows, name = j["fmt"], j["rows"], j["name"]
        clock = time.time()             # time only the Revit export
        try:
            j["run"]()
            seconds = time.time() - clock
            if j["kind"] == "file":
                self._record(fmt, job_rows, name, True, seconds=seconds,
                             detail=u"combined" if len(job_rows) > 1 else u"")
            else:                       # background: files arrive later
                r["timings"].append({"fmt": core.FORMAT_LABELS[fmt],
                                     "name": u"start: " + name, "count": len(job_rows),
                                     "seconds": seconds, "ok": True})
                r["bg_targets"] = j["targets"]
                self._set_progress(job_rows, fmt, u"wait", u"queued",
                                   u"Waiting for Revit's background PDF process")
                r["bg"] = BackgroundCollector(self.doc.Application, r["stage"], j["targets"],
                                              self._bg_file, self._bg_done, self._bg_tick)
                r["bg"].start()
                self.f("ResultText").Text = u"Revit is writing {0} PDFs in the background...".format(
                    len(job_rows))
        except Exception as ex:
            seconds = time.time() - clock
            reason = friendly_error(ex)
            if j["kind"] == "file":
                self._record(fmt, job_rows, name, False, reason, seconds)
            else:
                for row in job_rows:
                    self._record(fmt, [row], name, False, reason)
        r["index"] += 1

        if r["index"] < len(r["jobs"]) and not self.stop[0]:
            self._show_next()
            self.ext_event.Raise()      # next job in a NEW event, after Revit idles
        else:
            self._end_jobs()

    def _end_jobs(self):
        """No more jobs to start: finish now, or once the background PDFs are in."""
        r = self.run
        if r is None:
            return
        bg = r.get("bg")
        if bg is not None and not bg.done:
            if self.stop[0]:
                bg.abort()              # calls _bg_done -> _finish
            else:
                self.f("ResultText").Text = u"Waiting for Revit's background PDFs  ({0} of {1} files done)".format(
                    r["done"] + r["failed"], r["files"])
            return
        self._finish()

    def _bg_file(self, target, ok, reason, seconds):
        """BackgroundCollector: one PDF arrived (or failed)."""
        if self.run is None:
            return
        self._record("pdf", [target["row"]], target["name"], ok, reason, seconds,
                     count=1, detail=u"background")
        self.f("ResultText").Text = u"Background PDFs: {0} of {1} files done".format(
            self.run["done"] + self.run["failed"], self.run["files"])

    def _bg_tick(self, pending, seconds):
        """Every second while background PDFs are pending: the next one in
        sheet order gets the amber bar and a live timer (the window isn't
        blocked here, unlike during a normal export)."""
        r = self.run
        if r is None:
            return
        for t in r.get("bg_targets", []):
            if t["key"] in pending:
                self._busy([t["row"]], "pdf", core.fmt_seconds(seconds))
                return

    def _bg_done(self):
        """BackgroundCollector finished; end the run if the other jobs are done too."""
        r = self.run
        if r is None:
            return
        if r["index"] >= len(r["jobs"]) or self.stop[0]:
            self._finish()

    def request_stop(self):
        self.stop[0] = True
        self.f("BtnStop").IsEnabled = False
        self.f("ResultText").Text = u"Stopping after the current file..."
        r = self.run
        if r is not None and r["index"] >= len(r["jobs"]):
            self._end_jobs()            # only background PDFs left: stop collecting now

    def _finish(self):
        """End of the run (all done, stopped or model closed): summary, log, folder."""
        r = self.run
        if r is None:
            self._set_busy(False)
            return
        bg = r.get("bg")
        if bg is not None and not bg.done:
            bg.abort()                  # re-enters _finish through _bg_done
            if self.run is None:
                return
        self.run = None
        self.handler.step = None
        self._set_busy(False)
        # stopped early: nothing may stay amber / waiting
        self.suppress[0] = True
        try:
            for row in self.table.Rows:
                for p in FMT_PREFIX.values():
                    if row[p + "State"] in (u"wait", u"busy"):
                        row[p + "State"] = u""
                        row[p + "Text"] = u"skipped"
                        row[p + "Tip"] = u"Not exported - the run was stopped"
        finally:
            self.suppress[0] = False
        s = r["s"]
        total = time.time() - r["clock"]
        done, failed, failures = r["done"], r["failed"], r["failures"]
        skipped = r["files"] - done - failed
        summary = u"{0} written, {1} failed".format(bd.plural(done, u"file"), failed)
        if skipped:
            summary += u", {0} skipped (stopped)".format(skipped)
        summary += u"  in {0}".format(core.fmt_seconds(total))
        slow = core.slowest([t for t in r["timings"] if not t["name"].startswith(u"start: ")], 1)
        if slow:
            summary += u"   |   slowest: {0} {1} ({2})".format(
                slow[0]["fmt"], slow[0]["name"], core.fmt_seconds(slow[0]["seconds"]))
        for note in r["notes"]:
            summary += u"   |   " + note
        self.f("ResultText").Text = summary
        self._write_log(s, r["timings"], total, r["started"], r["notes"])
        if r["stage"] and not (bg is not None and bg.aborted):
            # after a Stop, Revit's background process may still be writing there;
            # clean_stages() removes that folder on a later run instead
            shutil.rmtree(r["stage"], ignore_errors=True)
        if failures:
            say(u"{0} of {1} files failed".format(failed, r["files"]),
                u"\n".join(failures[:12]) + (u"\n..." if len(failures) > 12 else u""))
        if done and s["open_folder"]:
            try:
                System.Diagnostics.Process.Start(u"explorer.exe", u'"{0}"'.format(s["folder"]))
            except Exception:
                pass

    def _write_log(self, s, timings, total, started, notes=()):
        """Save the run's seconds-per-file CSV and enable 'Open timing log'.
        Rewritten after every file, so a stopped or crashed run keeps its data."""
        if not timings:
            return
        by_fmt = {}
        for t in timings:
            if not t["name"].startswith(u"start: "):
                by_fmt.setdefault(t["fmt"], []).append(t["seconds"])
        engine = (u"Revit background export" if s["pdf_background"]
                  else u"one Revit call per sheet")
        averages = u", ".join(u"{0} {1} avg over {2}".format(
            fmt, core.fmt_seconds(sum(v) / len(v)), len(v)) for fmt, v in sorted(by_fmt.items()))
        header = [u"Model: {0}".format(self.resolver.model),
                  u"Started: {0}".format(started.strftime("%Y-%m-%d %H:%M:%S")),
                  u"Revit: {0}".format(bd.revit_version(self.doc)),
                  u"Total: {0}   ({1})".format(core.fmt_seconds(total), averages),
                  u"PDF: {0} DPI, {1}, raster quality {2}, {3}".format(
                      s["pdf_dpi"], u"raster" if s["pdf_raster"] else u"vector",
                      s["pdf_quality"], s["pdf_output"]),
                  u"PDF engine: {0}".format(engine),
                  u"Folder: {0}".format(s["folder"])] + [u"Note: " + n for n in notes]
        path = os.path.join(core.LOG_DIR, core.log_name(self.resolver.model, started))
        try:
            core.write_timing_log(path, timings, header)
            core.prune_logs()
            self.last_log = path
            self.f("BtnOpenLog").IsEnabled = True
        except Exception as ex:
            self.f("ResultText").Text += u"   (timing log not saved: {0})".format(friendly_error(ex))

    def open_log(self):
        path = getattr(self, "last_log", None)
        if path and os.path.exists(path):
            # explorer.exe opens it in the default app (Excel) on .NET 4.8 and
            # .NET 8 alike; Process.Start(path) alone fails on Revit 2025+.
            try:
                System.Diagnostics.Process.Start(u"explorer.exe", u'"{0}"'.format(path))
            except Exception:
                pass

    def on_closed(self, sender, e):
        """Window gone: forget it, so the button opens a fresh one next time."""
        self.handler.step = None
        for key in (ENV_WINDOW, ENV_HANDLER, ENV_EVENT):
            envvars.set_pyrevit_env_var(key, None)
        try:
            self.ext_event.Dispose()
        except Exception:
            pass

    def show(self):
        """Modeless: the script returns and Revit stays usable while the
        window is open. Kept on top of Revit through its owner handle."""
        from System.Windows.Interop import WindowInteropHelper
        enable_combo_search(self.w)
        try:
            WindowInteropHelper(self.w).Owner = uiapp.MainWindowHandle
        except Exception:
            pass
        self.w.Closed += System.EventHandler(self.on_closed)
        envvars.set_pyrevit_env_var(ENV_WINDOW, self.w)
        self.w.Show()


# =============================================================================
# MAIN
# =============================================================================
# Already open? Bring that window to the front instead of opening a second one.
_open = envvars.get_pyrevit_env_var(ENV_WINDOW)
if _open is not None:
    try:
        if _open.IsLoaded:
            _open.Activate()
            script.exit()
    except Exception:
        pass
    envvars.set_pyrevit_env_var(ENV_WINDOW, None)

if doc.IsFamilyDocument:
    bd.alert(u"Open a project to export its sheets and views.", TITLE, exit=True)

ITEMS = collect_items(doc)
if not ITEMS["sheets"] and not ITEMS["views"]:
    bd.alert(u"This model has no sheets or printable views.", TITLE, exit=True)

# The ExternalEvent must be created here, inside the button's command. A fresh
# one per window; kept in envvars too so nothing is garbage-collected early.
HANDLER = ExportHandler()
EVENT = ExternalEvent.Create(HANDLER)
envvars.set_pyrevit_env_var(ENV_HANDLER, HANDLER)
envvars.set_pyrevit_env_var(ENV_EVENT, EVENT)

ExportWindow(doc, ITEMS, core.load_store(), HANDLER, EVENT).show()

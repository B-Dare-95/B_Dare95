# -*- coding: utf-8 -*-
"""DLC Export Sheets - batch export sheets/views to PDF and DWG in one run.

ProSheets-style workflow, built on Revit's native exporters (no PDF printer):
  1. Selection  - sheets or views, search, Revit View/Sheet Sets, saved sets,
                  Project Browser selection, open views
  2. Naming     - build file names from any sheet / title block / project
                  information / shared parameter, with separators, prefix,
                  suffix and live preview
  3. PDF        - paper size (auto from title block), orientation, placement,
                  zoom, vector/raster, colours, quality, all hide options,
                  separate / combined / both
  4. DWG        - any Revit DWG export setup, merged or xref, .pcp clean-up
  5. Export     - one root folder with tokens, PDF/DWG sub-folders,
                  existing-file policy, temporary view mode reset, profiles

One dialog, then the whole batch runs unattended. Each file is isolated: a
failure is logged and the batch carries on.

Author : Ahmed Sedki - DLC
Engine : IronPython 2.7, Revit 2025 / 2026
"""
import datetime
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pyrevit import forms, revit  # noqa: E402

import dlc_export_core as core  # noqa: E402
import dlc_export_progress as progress  # noqa: E402
import dlc_export_revit as rx  # noqa: E402
import dlc_export_ui as ui  # noqa: E402

__title__ = "Export\nPDF + DWG"
__author__ = "Ahmed Sedki - DLC"
# keep this script's engine alive after it returns: the progress window keeps
# collecting PDFs from Revit's background export and answering dialogs
__persistentengine__ = True

# ---------------------------------------------------------------------------
# Firm-level settings (edit here, no logic changes needed)
# ---------------------------------------------------------------------------
SETTINGS = {
    # where the last-used settings are remembered (per user)
    "settings_file": os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                                  "DLC", "ExportSheets", "settings.json"),
    # optional firm profile loaded when a user has no saved settings yet
    # e.g. r"\\server\BIM\pyRevit\DLC Export Profile.json"  (leave blank for none)
    "firm_default_profile": "",
    # where the timing logs (CSV) go
    "log_folder": os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                               "DLC", "ExportSheets", "logs"),
}


def _initial_settings():
    path = SETTINGS["settings_file"]
    if os.path.isfile(path):
        return core.load_settings(path)
    firm = SETTINGS["firm_default_profile"]
    if firm and os.path.isfile(firm):
        return core.load_settings(firm)
    return core.default_settings()


def _persist(settings):
    try:
        core.save_settings(SETTINGS["settings_file"], settings)
    except Exception:
        pass   # remembering settings must never block an export


def _export_root(jobs, settings):
    """Folder to show at the end: the common root above PDF/DWG sub-folders."""
    live = [j for j in jobs if j.status != "failed"] or jobs
    if not live:
        return None
    folder = live[0].folder
    if settings["output"]["split_by_format"]:
        folder = os.path.dirname(folder)
    return folder


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if doc is None:
        forms.alert(u"Open a Revit project first.", exitscript=True)
    if doc.IsFamilyDocument:
        forms.alert(u"This tool exports sheets and views from a project, not a family.",
                    exitscript=True)
    if not hasattr(rx.DB, "PDFExportOptions"):
        forms.alert(u"Native PDF export needs Revit 2022 or newer.", exitscript=True)

    settings = _initial_settings()
    project = rx.project_info(doc)
    cache = {}

    def collect(mode):
        if mode not in cache:
            items, catalog, _p = rx.collect(doc, mode)
            cache[mode] = (items, catalog)
        return cache[mode]

    ctx = {
        "settings": settings,
        "collect": collect,
        "project": project,
        "sheet_sets": rx.sheet_sets(doc),
        "browser_ids": rx.browser_selection(uidoc),
        "open_ids": rx.open_view_ids(uidoc),
        "dwg_setups": rx.dwg_setups(doc),
        "paper_formats": rx.paper_formats(),
        "fill_time": rx.fill_time_values,
        "persist": _persist,
    }

    win = ui.ExportWindow(ctx)
    win.ShowDialog()
    if not win.result:
        return
    settings, items = win.result
    _persist(settings)

    now = datetime.datetime.now()
    rx.fill_time_values(items, now)
    jobs = core.plan_jobs(items, settings, project, now=now)
    log = []

    run = rx.ExportRun()
    t0 = rx.time.time()
    rx.prepare_views(doc, [it["id"] for it in items], settings["prep"], log)
    run.phase(u"Reset temporary view modes", t0)

    links = rx.loaded_links(doc)
    if links[0]:
        log.append(u"This model has %d loaded Revit link(s); every view on every sheet draws "
                   u"them, which is usually the main export time." % links[0])

    win = progress.ProgressWindow()
    win.root_folder = _export_root(jobs, settings)
    win.notes = log                      # notes appear in the window as they happen
    win.Show()

    guard = None
    if settings["output"].get("auto_dialogs", True):
        guard = rx.DialogGuard(_uiapp(), run.dialogs)
        guard.start()

    try:
        rx.run_jobs(doc, jobs, settings, win, log, run)
    finally:
        # FIX 1.2.1: stop auto-answering dialogs NOW, while we are still inside
        # the Revit command. Before, the guard stayed subscribed until the last
        # background PDF arrived (or 10 min stall) - and if unsubscribing from the
        # timer failed (outside API context) it stayed on for the whole session,
        # silently pressing OK/Close/CANCEL on every Revit dialog, including
        # "Save changes?" when closing Revit -> Revit refused to close.
        if guard is not None:
            guard.stop()

    if run.tracker is not None:
        run.tracker_started = rx.time.time()
        # FIX 1.2.1: start the stall clock when collecting starts, not when the
        # background export was launched (the DWG phase ran in between).
        run.tracker.last_progress = run.tracker.last_done = run.tracker_started

    def done():
        if run.tracker is not None:
            run.phase(u"Waiting for background PDFs", run.tracker_started)
            stage_root = getattr(run.tracker, "stage_root", None)
            if stage_root:
                rx.shutil.rmtree(stage_root, ignore_errors=True)
        if run.dialogs:
            log.append(u"%d Revit dialog(s) were answered automatically (listed in the timing "
                       u"log)." % len(run.dialogs))
        run.phases.append((u"Total", rx.time.time() - run.started))
        if settings["output"].get("timing_log", True):
            try:
                name = u"DLC Export %s.csv" % now.strftime("%Y-%m-%d %H%M%S")
                win.log_path = core.write_timing_log(
                    os.path.join(SETTINGS["log_folder"], name),
                    rx.run_meta(doc, settings, jobs, links), run.phases, jobs, run.dialogs)
            except Exception as ex:
                log.append(u"Timing log not saved: %s" % ex)
        counts = core.summarize(jobs)
        if settings["output"]["open_folder"] and counts["ok"] and win.root_folder \
                and os.path.isdir(win.root_folder):
            progress.open_folder(win.root_folder)

    # returns at once when there is no background export; otherwise the window
    # finishes by itself when the last PDF arrives (Revit stays usable meanwhile)
    win.complete_when_done(run.tracker, done)
    return jobs


def _uiapp():
    try:
        return revit.HOST_APP.uiapp
    except Exception:
        return globals().get("__revit__")


if __name__ == "__main__":
    main()

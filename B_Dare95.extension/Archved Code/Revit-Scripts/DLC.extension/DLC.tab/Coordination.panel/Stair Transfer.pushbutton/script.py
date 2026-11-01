# -*- coding: utf-8 -*-
"""
DLC Stair Transfer v1.3.0

Copies (multistorey) stairs from the architecture model into the structure
model. Every flight becomes its own stair on the structural slab levels, with
each end dropped by that floor's finish thickness so the stair runs
slab-to-slab.

Method (v1.2): each flight is REBUILT in the structure model from the arch
stair's runs and landings (Revit refuses to copy stairs that belong to a
multistorey stair). Flights with non-straight runs fall back to copying.

Three ways to choose the stairs:
  * select them in the ARCH model's view (pre-select, click or window) and
    paste into another open model (the structure model);
  * run from the STRUCTURE model and pick them in the linked arch model;
  * run from the STRUCTURE model and choose them from a list.

IronPython 2.7 / pyRevit, Revit 2025-2026.
"""
__title__ = "Stair\nTransfer"
__author__ = "DLC"
__doc__ = ("Copy multistorey stairs from the architecture model into the "
           "structure model, one stair per flight, re-hosted on structural "
           "levels and dropped to slab level.")

from pyrevit import revit, DB, forms, script

from Autodesk.Revit.DB.Architecture import (Stairs, MultistoryStairs,
                                            StairsRun, StairsLanding,
                                            StairsRunJustification)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

from dlc_stairxfer import engine

# ---------------------------------------------------------------------------
# SETTINGS - firm-level options. Lengths in millimetres.
# ---------------------------------------------------------------------------
SETTINGS = {
    # SLAB_TO_SLAB : base drops by the base-floor finish, top drops by the
    #                top-floor finish (riser height adjusts, tread count kept)
    # SHIFT_BY_BASE: whole flight drops by the base-floor finish only
    "GEOMETRY_MODE": engine.MODE_SLAB_TO_SLAB,

    # A structural level is accepted for an arch level if it sits between
    # MATCH_TOL_MM above and MAX_FINISH_MM below the arch level.
    "MAX_FINISH_MM": 600.0,
    "MATCH_TOL_MM": 5.0,

    # Default choice in the level dialog when "nearest below" is wrong
    # (you can still change it in the dialog), e.g.
    # {"L05 FFL": "L05 SSL", "ROOF FFL": "ROOF SSL"}
    "LEVEL_NAME_MAP": {},

    # In the level dialog, prefer structural levels whose name contains
    # this text as the default choice (blank = nearest below). e.g. "SSL"
    "STR_LEVEL_NAME_CONTAINS": "",

    # REBUILD: build each flight from the arch geometry (works for
    #          multistorey stairs; non-straight runs fall back to COPY)
    # COPY   : copy the arch stair element (fails for multistorey members)
    "METHOD": "REBUILD",

    # Copy railings hosted on each flight (COPY method only; rebuilt stairs
    # get no railings - not needed in the structure model).
    "COPY_RAILINGS": True,

    # Use this stair type in the STR model ("" = bring the arch type over).
    "TARGET_STAIR_TYPE": "",

    # Delete levels that Revit created during the copy and nothing uses.
    "DELETE_UNUSED_COPIED_LEVELS": True,

    # Flag flights whose height changes more than this.
    "HEIGHT_CHANGE_WARN_MM": 50.0,

    # True = show the preview and stop without changing the model.
    "DRY_RUN": False,
}

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
INVALID = DB.ElementId.InvalidElementId
BIP = DB.BuiltInParameter


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def eid_val(eid):
    try:
        return eid.Value          # Revit 2024+
    except AttributeError:
        return eid.IntegerValue


def valid_id(eid):
    return eid is not None and eid != INVALID


def el_name(el):
    try:
        return DB.Element.Name.GetValue(el)
    except Exception:
        try:
            return el.Name
        except Exception:
            return "?"


def p_double(el, bip, default=0.0):
    p = el.get_Parameter(bip)
    return p.AsDouble() if p is not None and p.HasValue else default


def p_id(el, bip):
    p = el.get_Parameter(bip)
    return p.AsElementId() if p is not None else INVALID


def set_p(el, bip, value):
    p = el.get_Parameter(bip)
    if p is None or p.IsReadOnly:
        raise Exception("Parameter %s is missing or read-only on stair %s"
                        % (bip, eid_val(el.Id)))
    p.Set(value)


def stop(msg, title="Stair Transfer"):
    forms.alert(msg, title=title, exitscript=True)


def is_stair_like(el):
    return isinstance(el, (Stairs, MultistoryStairs, StairsRun, StairsLanding))


class Source(object):
    """An architecture document plus the transform into the STR model."""

    def __init__(self, sdoc, xform, label):
        self.doc = sdoc
        self.xform = xform
        self.label = label

    def z(self, internal_z):
        return self.xform.OfPoint(DB.XYZ(0, 0, internal_z)).Z


class Job(object):
    """One flight to copy."""

    def __init__(self, src, stairs, dz, flight, railing_ids):
        self.src = src
        self.stairs = stairs
        self.dz = dz
        self.flight = flight
        self.railing_ids = railing_ids


class UseDestinationTypes(DB.IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        return DB.DuplicateTypeAction.UseDestinationTypes


class WarningCollector(DB.IFailuresPreprocessor):
    """Deletes warnings (listing them in the report) and records errors so
    their text reaches the user instead of a silent rollback."""

    def __init__(self):
        self.messages = []
        self.errors = []

    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                self.messages.append(f.GetDescriptionText())
                fa.DeleteWarning(f)
            else:
                self.errors.append(f.GetDescriptionText())
        return DB.FailureProcessingResult.Continue


class LinkedStairFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, DB.RevitLinkInstance)

    def AllowReference(self, ref, pt):
        try:
            li = doc.GetElement(ref.ElementId)
            ldoc = li.GetLinkDocument()
            if ldoc is None:
                return False
            return is_stair_like(ldoc.GetElement(ref.LinkedElementId))
        except Exception:
            return False


class StairPickFilter(ISelectionFilter):
    """Picking in the active (arch) model: stairs, multistorey stairs, runs
    and landings."""

    def AllowElement(self, e):
        return is_stair_like(e)

    def AllowReference(self, ref, pt):
        return False


ROUTE_HERE = "Select stairs in THIS model -> paste into another open model"
ROUTE_LINK = "Pick stairs in a LINKED model -> paste into this model"
ROUTE_LIST = "Choose stairs from a LIST (other open model) -> this model"


def stairs_in_selection():
    """Stair-like elements already selected in the active view."""
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return []
    out = []
    for i in ids:
        e = revit.doc.GetElement(i)
        if e is not None and is_stair_like(e):
            out.append(e)
    return out


def pick_here(preselected):
    """[(element, pick point or None)] from the active model."""
    if preselected:
        return [(e, None) for e in preselected]
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, StairPickFilter(),
            "Select the stairs to copy (click, or drag a window), then "
            "Finish. Tab to pick a single flight of a multistorey stair.")
    except OperationCanceledException:
        script.exit()
    return [(revit.doc.GetElement(r.ElementId), getattr(r, "GlobalPoint",
                                                         None))
            for r in refs]


def choose_target_doc(source_doc, n_picked):
    docs = [d for d in source_doc.Application.Documents
            if not d.IsLinked and not d.IsFamilyDocument
            and d.Title != source_doc.Title]
    if not docs:
        stop("Open the structure model in this Revit session too, then run "
             "again - the stairs are pasted into another open model.")
    by_title = dict((d.Title, d) for d in docs)
    title = forms.SelectFromList.show(
        sorted(by_title.keys()),
        title="Paste %d selected stair element(s) into which model?"
              % n_picked,
        button_name="Paste here")
    if not title:
        script.exit()
    target = by_title[title]
    if getattr(target, "IsReadOnly", False):
        stop("'%s' is read-only. Open it editable and run again." % title)
    return target


# ---------------------------------------------------------------------------
# Coordinates for the "open document" route
# ---------------------------------------------------------------------------
def internal_to_shared(d):
    """Transform internal -> shared for document d, verified against
    GetProjectPosition so the direction is never guessed."""
    loc = d.ActiveProjectLocation
    t = loc.GetTotalTransform()
    probe = DB.XYZ(10.0, 20.0, 3.0)
    pp = loc.GetProjectPosition(probe)
    target = DB.XYZ(pp.EastWest, pp.NorthSouth, pp.Elevation)
    for cand in (t, t.Inverse):
        if cand.OfPoint(probe).DistanceTo(target) < 1e-4:
            return cand
    return None


def transform_for_open_doc(sdoc):
    # 1) a link instance of this model in the STR model - most reliable
    stem = sdoc.Title.lower().replace(".rvt", "")
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        lt = doc.GetElement(li.GetTypeId())
        lname = el_name(lt).lower().replace(".rvt", "")
        if lname.startswith(stem) or stem.startswith(lname):
            return li.GetTotalTransform(), "link instance '%s'" % el_name(lt)
    # 2) shared coordinates
    ts = internal_to_shared(sdoc)
    td = internal_to_shared(doc)
    if ts is None or td is None:
        return None, None
    return td.Inverse.Multiply(ts), "shared coordinates"


# ---------------------------------------------------------------------------
# Step 1 - get the source stairs
# ---------------------------------------------------------------------------
def pick_from_link():
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedStairFilter(),
            "Pick the architecture stair(s) in the link, then Finish")
    except OperationCanceledException:
        script.exit()
    picked = []   # (Source, element)
    sources = {}
    for r in refs:
        li = doc.GetElement(r.ElementId)
        ldoc = li.GetLinkDocument()
        key = eid_val(li.Id)
        if key not in sources:
            sources[key] = Source(ldoc, li.GetTotalTransform(),
                                  el_name(li))
        gp = getattr(r, "GlobalPoint", None)   # host coordinates
        picked.append((sources[key], ldoc.GetElement(r.LinkedElementId),
                       None if gp is None else gp.Z))
    return picked


def choose_from_open_doc():
    docs = [d for d in doc.Application.Documents
            if not d.IsLinked and not d.IsFamilyDocument
            and d.PathName != doc.PathName and d.Title != doc.Title]
    if not docs:
        stop("No other project is open. Open the architecture model, or link "
             "it into this structure model and use the link option.")
    by_title = dict((d.Title, d) for d in docs)
    title = forms.SelectFromList.show(sorted(by_title.keys()),
                                      title="Architecture model",
                                      button_name="Use this model")
    if not title:
        script.exit()
    sdoc = by_title[title]
    xform, how = transform_for_open_doc(sdoc)
    if xform is None:
        stop("Could not line up '%s' with this model: no link instance of it "
             "here and the shared coordinates could not be verified.\n\n"
             "Link the architecture model into this model (any position by "
             "shared coordinates) and run again." % title)
    src = Source(sdoc, xform, "%s (%s)" % (title, how))

    cats = [DB.BuiltInCategory.OST_Stairs]
    ms_cat = getattr(DB.BuiltInCategory, "OST_MultistoryStairs", None)
    if ms_cat is not None:
        cats.append(ms_cat)
    options = {}
    for cat in cats:
        col = (DB.FilteredElementCollector(sdoc).OfCategory(cat)
               .WhereElementIsNotElementType())
        for el in col:
            if isinstance(el, MultistoryStairs):
                n = el.GetAllStairsIds().Count
                label = "Multistorey stair #%d  (%d stair group(s))" % (
                    eid_val(el.Id), n)
            elif isinstance(el, Stairs):
                if valid_id(getattr(el, "MultistoryStairsId", INVALID)):
                    continue  # offered through its multistorey parent
                b = sdoc.GetElement(p_id(el, BIP.STAIRS_BASE_LEVEL_PARAM))
                t = sdoc.GetElement(p_id(el, BIP.STAIRS_TOP_LEVEL_PARAM))
                label = "Stair #%d  %s  %s -> %s" % (
                    eid_val(el.Id), el_name(sdoc.GetElement(el.GetTypeId())),
                    el_name(b) if b else "?", el_name(t) if t else "(height)")
            else:
                continue
            options[label] = el
    if not options:
        stop("No stairs found in '%s'." % title)
    chosen = forms.SelectFromList.show(sorted(options.keys()),
                                       title="Stairs to copy",
                                       multiselect=True,
                                       button_name="Copy these")
    if not chosen:
        script.exit()
    return [(src, options[c]) for c in chosen]


# ---------------------------------------------------------------------------
# Step 2 - expand picks into individual flights
# ---------------------------------------------------------------------------
def collect_jobs(picked):
    """picked: [(Source, element)] or [(Source, element, pick z host)].

    A MultistoryStairs gives all its flights. A single Stairs (or a run /
    landing of it) gives just that stair; if it is a pinned group placed on
    several floors, the pick height chooses the floor (no point -> all).
    """
    jobs = []
    seen_ms = set()
    seen_st = set()
    for item in picked:
        src, el = item[0], item[1]
        pick_z = item[2] if len(item) > 2 else None
        sdoc = src.doc
        if isinstance(el, (StairsRun, StairsLanding)):
            el = el.GetStairs()
        if isinstance(el, Stairs):
            msid = getattr(el, "MultistoryStairsId", INVALID)
            lvls = []
            if valid_id(msid):
                ms = sdoc.GetElement(msid)
                try:
                    lvls = [sdoc.GetElement(i) for i in
                            ms.GetStairsPlacementLevels(el)]
                except Exception:
                    lvls = []
            jobs.extend(jobs_for_stair(src, el, lvls, seen_st, pick_z))
            continue
        if isinstance(el, MultistoryStairs):
            k = (id(sdoc), eid_val(el.Id))
            if k in seen_ms:
                continue
            seen_ms.add(k)
            for sid in el.GetAllStairsIds():
                st = sdoc.GetElement(sid)
                lvls = [sdoc.GetElement(i) for i in
                        el.GetStairsPlacementLevels(st)]
                jobs.extend(jobs_for_stair(src, st, lvls, seen_st))
    return jobs


def jobs_for_stair(src, st, placement_levels, seen, pick_z=None):
    sdoc = src.doc
    base_lvl = sdoc.GetElement(p_id(st, BIP.STAIRS_BASE_LEVEL_PARAM))
    if base_lvl is None:
        output.print_md("- Stair #%d skipped: it has no base level."
                        % eid_val(st.Id))
        return []
    base_elev = src.z(base_lvl.ProjectElevation)
    base_off = p_double(st, BIP.STAIRS_BASE_OFFSET)
    top_lvl = sdoc.GetElement(p_id(st, BIP.STAIRS_TOP_LEVEL_PARAM))
    if top_lvl is not None:
        top_elev = src.z(top_lvl.ProjectElevation)
        top_off = p_double(st, BIP.STAIRS_TOP_OFFSET)
    else:
        top_elev = None
        top_off = st.Height
    stype = sdoc.GetElement(st.GetTypeId())
    max_riser = getattr(stype, "MaxRiserHeight", None)
    try:
        rails = list(st.GetAssociatedRailings())
    except Exception:
        rails = []

    dzs = engine.expand_placements(
        eid_val(st.Id), base_elev,
        [src.z(l.ProjectElevation) for l in placement_levels if l])
    if pick_z is not None:
        bottom = base_elev + base_off
        top = (top_elev + top_off) if top_elev is not None \
            else bottom + top_off
        dzs = engine.placements_at(dzs, bottom, top - bottom, pick_z)
    jobs = []
    for dz in dzs:
        k = (id(sdoc), eid_val(st.Id), round(dz, 6))
        if k in seen:
            continue
        seen.add(k)
        label = "#%d%s" % (eid_val(st.Id),
                           "" if abs(dz) < 1e-6 else
                           " @%+.0f" % engine.to_mm(dz))
        flight = engine.FlightSource(
            key=k, label=label, base_elev=base_elev, base_offset=base_off,
            top_elev=top_elev, top_offset=top_off,
            risers=st.ActualRisersNumber, max_riser=max_riser, dz=dz)
        jobs.append(Job(src, st, dz, flight, rails))
    return jobs


# ---------------------------------------------------------------------------
# Step 3 - level mapping: which arch floors to copy, which STR level each
# one pastes to
# ---------------------------------------------------------------------------
LEVEL_MAP_XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Stair Transfer - choose levels" Width="760" SizeToContent="Height"
    MaxHeight="780" WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip" FontFamily="Segoe UI" FontSize="12"
    ShowInTaskbar="False">
  <DockPanel Margin="14">
    <TextBlock DockPanel.Dock="Top" TextWrapping="Wrap" Margin="0,0,0,10"
               Foreground="#333">
      Tick the floors to copy (a flight is copied from the level it starts
      on). For each architecture level, choose the structural level it
      pastes to. Only structural levels on the same floor are offered.
    </TextBlock>
    <DockPanel DockPanel.Dock="Bottom" Margin="0,12,0,0" LastChildFill="False">
      <TextBlock x:Name="summary" DockPanel.Dock="Left"
                 VerticalAlignment="Center" Foreground="#555"/>
      <Button x:Name="btn_cancel" DockPanel.Dock="Right" Content="Cancel"
              Width="80" IsCancel="True"/>
      <Button x:Name="btn_ok" DockPanel.Dock="Right" Content="Preview"
              Width="90" IsDefault="True" Margin="0,0,6,0"/>
      <Button x:Name="btn_none" DockPanel.Dock="Right" Content="Untick all"
              Width="80" Margin="0,0,16,0"/>
      <Button x:Name="btn_all" DockPanel.Dock="Right" Content="Tick all"
              Width="80" Margin="0,0,6,0"/>
    </DockPanel>
    <ScrollViewer VerticalScrollBarVisibility="Auto">
      <Grid x:Name="grid" Margin="0,0,4,0"/>
    </ScrollViewer>
  </DockPanel>
</Window>"""

CFG_SECTION = "DLC_StairTransfer"


def load_saved_choices():
    """Last run's choices: ({arch name: str name}, set(unticked arch names))."""
    import json
    try:
        cfg = script.get_config(CFG_SECTION)
        mapping = json.loads(cfg.get_option("level_map", "{}") or "{}")
        unticked = set(json.loads(cfg.get_option("unticked", "[]") or "[]"))
        return mapping, unticked
    except Exception:
        return {}, set()


def save_choices(rows, copy_keys, level_map):
    import json
    try:
        mapping, unticked = load_saved_choices()
        for r in rows:
            target = level_map.get(r.arch.key)
            if target is not None:
                mapping[r.arch.name] = target.name
            if r.is_base:
                if r.arch.key in copy_keys:
                    unticked.discard(r.arch.name)
                else:
                    unticked.add(r.arch.name)
        cfg = script.get_config(CFG_SECTION)
        cfg.level_map = json.dumps(mapping)
        cfg.unticked = json.dumps(sorted(unticked))
        script.save_config()
    except Exception:
        pass  # remembering choices is a convenience, never a blocker


def ask_level_map(rows, flights, arch_levels, unticked):
    """Show the mapping dialog. Returns (copy_keys, level_map) or None."""
    import clr
    for asm in ("PresentationFramework", "PresentationCore", "WindowsBase"):
        try:
            clr.AddReference(asm)
        except Exception:
            pass
    from System.Windows import (Thickness, GridLength, GridUnitType,
                                FontWeights, VerticalAlignment)
    from System.Windows import Controls as C
    from System.Windows.Media import Brushes

    max_finish = engine.mm(SETTINGS.get("MAX_FINISH_MM", 600.0))
    NONE_LABEL = "(not mapped)"

    class LevelMapWindow(forms.WPFWindow):
        def __init__(self):
            try:
                forms.WPFWindow.__init__(self, LEVEL_MAP_XAML,
                                         literal_string=True)
            except TypeError:  # older pyRevit: needs a file
                import os
                import tempfile
                path = os.path.join(tempfile.gettempdir(),
                                    "dlc_stair_transfer_levels.xaml")
                with open(path, "w") as fh:
                    fh.write(LEVEL_MAP_XAML)
                forms.WPFWindow.__init__(self, path)
            self.result = None
            self.checks = {}
            self.combos = {}
            self.finish_tb = {}
            self._build()
            self.btn_ok.Click += self._ok
            self.btn_all.Click += lambda s, e: self._tick_all(True)
            self.btn_none.Click += lambda s, e: self._tick_all(False)
            self._refresh()

        def _cell(self, el, r, c):
            C.Grid.SetRow(el, r)
            C.Grid.SetColumn(el, c)
            self.grid.Children.Add(el)

        def _text(self, txt, r, c, bold=False, gray=False):
            tb = C.TextBlock()
            tb.Text = txt
            tb.VerticalAlignment = VerticalAlignment.Center
            tb.Margin = Thickness(4, 3, 4, 3)
            if bold:
                tb.FontWeight = FontWeights.SemiBold
            if gray:
                tb.Foreground = Brushes.Gray
            self._cell(tb, r, c)
            return tb

        def _build(self):
            g = self.grid
            for w, star in ((48, False), (1, True), (80, False), (58, False),
                            (240, False), (130, False)):
                cd = C.ColumnDefinition()
                cd.Width = GridLength(w, GridUnitType.Star if star
                                      else GridUnitType.Pixel)
                g.ColumnDefinitions.Add(cd)
            for _ in range(len(rows) + 1):
                rd = C.RowDefinition()
                rd.Height = GridLength.Auto
                g.RowDefinitions.Add(rd)
            for c, h in enumerate(["Copy", "Arch level (copy from)",
                                   "Elev (mm)", "Flights",
                                   "Structural level (paste to)",
                                   "Finish (mm)"]):
                self._text(h, 0, c, bold=True)
            for i, r in enumerate(rows):
                ri = i + 1
                k = r.arch.key
                if r.is_base:
                    cb = C.CheckBox()
                    cb.IsChecked = r.arch.name not in unticked
                    cb.VerticalAlignment = VerticalAlignment.Center
                    cb.Margin = Thickness(10, 3, 4, 3)
                    cb.Checked += lambda s, e: self._refresh()
                    cb.Unchecked += lambda s, e: self._refresh()
                    self._cell(cb, ri, 0)
                    self.checks[k] = cb
                self._text(r.arch.name, ri, 1)
                self._text("%.0f" % engine.to_mm(r.arch.elev), ri, 2)
                self._text(str(r.n_flights) if r.is_base else "top only",
                           ri, 3, gray=not r.is_base)
                combo = C.ComboBox()
                combo.Margin = Thickness(4, 2, 4, 2)
                combo.Items.Add(NONE_LABEL)
                sel = 0
                for n, cand in enumerate(r.candidates):
                    combo.Items.Add("%s   (%.0f)" % (cand.name,
                                                     engine.to_mm(cand.elev)))
                    if r.suggested is not None and cand.key == r.suggested.key:
                        sel = n + 1
                combo.SelectedIndex = sel
                combo.SelectionChanged += lambda s, e: self._refresh()
                if not r.candidates:
                    combo.IsEnabled = False
                    combo.ToolTip = ("No structural level on this floor. "
                                     "Add one in the STR model.")
                self._cell(combo, ri, 4)
                self.combos[k] = combo
                self.finish_tb[k] = self._text("", ri, 5)

        def _choice(self, r):
            idx = self.combos[r.arch.key].SelectedIndex
            return r.candidates[idx - 1] if idx >= 1 else None

        def _state(self):
            copy_keys = set(k for k, cb in self.checks.items()
                            if cb.IsChecked)
            level_map = dict((r.arch.key, self._choice(r)) for r in rows)
            return copy_keys, level_map

        def _refresh(self):
            copy_keys, level_map = self._state()
            needed = set()
            for f in engine.select_flights(flights, arch_levels, copy_keys,
                                           SETTINGS):
                for a in engine.flight_ends(f, arch_levels, SETTINGS):
                    if a is not None:
                        needed.add(a.key)
            for r in rows:
                tb = self.finish_tb[r.arch.key]
                t = level_map.get(r.arch.key)
                in_use = r.arch.key in needed
                self.combos[r.arch.key].Opacity = 1.0 if in_use else 0.45
                if t is None:
                    tb.Text = "needed!" if in_use else "-"
                    tb.Foreground = Brushes.Firebrick if in_use \
                        else Brushes.Gray
                    continue
                fin = r.arch.elev - t.elev
                tb.Text = "%.0f" % engine.to_mm(fin)
                if fin < engine.mm(1.0):
                    tb.Text += "  same as FFL?"
                    tb.Foreground = Brushes.DarkOrange
                elif fin > max_finish:
                    tb.Text += "  very thick"
                    tb.Foreground = Brushes.DarkOrange
                else:
                    tb.Foreground = Brushes.Black if in_use else Brushes.Gray
            n = len(engine.select_flights(flights, arch_levels, copy_keys,
                                          SETTINGS))
            self.summary.Text = "%d of %d flight(s) selected" % (
                n, len(flights))

        def _tick_all(self, value):
            for cb in self.checks.values():
                cb.IsChecked = value
            self._refresh()

        def _ok(self, sender, args):
            copy_keys, level_map = self._state()
            if not engine.select_flights(flights, arch_levels, copy_keys,
                                         SETTINGS):
                forms.alert("Tick at least one floor to copy.",
                            title="Stair Transfer")
                return
            missing = engine.missing_mappings(flights, arch_levels,
                                              copy_keys, level_map, SETTINGS)
            if missing:
                forms.alert("Choose a structural level for:\n  " +
                            "\n  ".join(missing), title="Stair Transfer")
                return
            self.result = (copy_keys, level_map)
            self.Close()

    w = LevelMapWindow()
    w.ShowDialog()
    return w.result


# ---------------------------------------------------------------------------
# Step 4 - copy and re-host one flight
# ---------------------------------------------------------------------------
def find_stair_type(name):
    if not name:
        return None
    for t in DB.FilteredElementCollector(doc).OfClass(DB.ElementType):
        if t.Category is not None and \
                t.Category.Id == DB.ElementId(DB.BuiltInCategory.OST_Stairs) \
                and el_name(t) == name:
            return t
    return None


def apply_levels(st, plan, str_by_key):
    base = str_by_key[plan.base_level.key]
    top = str_by_key[plan.top_level.key]

    def top_first():
        set_p(st, BIP.STAIRS_TOP_LEVEL_PARAM, top.Id)
        set_p(st, BIP.STAIRS_TOP_OFFSET, plan.top_offset)
        set_p(st, BIP.STAIRS_BASE_LEVEL_PARAM, base.Id)
        set_p(st, BIP.STAIRS_BASE_OFFSET, plan.base_offset)

    def base_first():
        set_p(st, BIP.STAIRS_BASE_LEVEL_PARAM, base.Id)
        set_p(st, BIP.STAIRS_BASE_OFFSET, plan.base_offset)
        set_p(st, BIP.STAIRS_TOP_LEVEL_PARAM, top.Id)
        set_p(st, BIP.STAIRS_TOP_OFFSET, plan.top_offset)

    try:
        top_first()
        doc.Regenerate()
    except Exception as first_err:
        try:
            base_first()
            doc.Regenerate()
        except Exception as second_err:
            raise Exception("%s / %s" % (first_err, second_err))

    # keep the tread count; riser height takes up the height change
    p = st.get_Parameter(BIP.STAIRS_DESIRED_NUMBER_OF_RISERS)
    if p is not None and not p.IsReadOnly:
        try:
            p.Set(plan.source.risers)
            doc.Regenerate()
        except Exception:
            pass  # Revit keeps its own riser count; reported in the result


def copy_flight(job, plan, opts, str_by_key, target_type):
    ids = List[DB.ElementId]()
    ids.Add(job.stairs.Id)
    with_rails = bool(SETTINGS["COPY_RAILINGS"]) and len(job.railing_ids) > 0
    if with_rails:
        for rid in job.railing_ids:
            ids.Add(rid)
    xform = job.src.xform.Multiply(
        DB.Transform.CreateTranslation(DB.XYZ(0, 0, job.dz)))
    note = []
    try:
        new_ids = DB.ElementTransformUtils.CopyElements(
            job.src.doc, ids, doc, xform, opts)
    except Exception as ex:
        if not with_rails:
            raise StageError("copy", ex)
        note.append("railings not copied (%s)" % ex)
        ids = List[DB.ElementId]()
        ids.Add(job.stairs.Id)
        try:
            new_ids = DB.ElementTransformUtils.CopyElements(
                job.src.doc, ids, doc, xform, opts)
        except Exception as ex2:
            raise StageError("copy", ex2)

    new_st = None
    for nid in new_ids:
        e = doc.GetElement(nid)
        if isinstance(e, Stairs):
            new_st = e
            break
    if new_st is None:
        raise StageError("copy", "Revit copied the elements but no stair "
                                 "came through.")
    if valid_id(getattr(new_st, "MultistoryStairsId", INVALID)):
        note.append("copy still belongs to a multistorey container - check "
                    "it in 3D")

    if target_type is not None:
        try:
            new_st.ChangeTypeId(target_type.Id)
        except Exception as ex:
            raise StageError("change type", ex)
    try:
        apply_levels(new_st, plan, str_by_key)
    except Exception as ex:
        raise StageError("re-host on structural levels", ex)
    return new_st, note


class StageError(Exception):
    """An error tagged with the step it happened in."""

    def __init__(self, stage, err):
        Exception.__init__(self, "%s failed: %s" % (stage, err))


TMP_LEVEL_PREFIX = "DLC_TMP "


def ensure_copy_levels(jobs):
    """Give the copy a level at every arch elevation a flight starts or ends
    on.

    Revit refuses to paste a stair that belongs to a multistorey stair
    unless the destination has levels at the same heights ("level heights
    don't match"). Existing levels at those elevations are reused; missing
    ones are created as temporary levels and removed after re-hosting.
    Returns the ids of the temporary levels.
    """
    tol = engine.mm(0.5)
    have = [l.ProjectElevation for l in
            DB.FilteredElementCollector(doc).OfClass(DB.Level)]
    needed = []
    for j in jobs:
        f = j.flight
        zs = [f.base_elev + f.dz]
        if f.top_elev is not None:
            zs.append(f.top_elev + f.dz)
        for z in zs:
            if not any(abs(z - e) <= tol for e in have + needed):
                needed.append(z)
    created = []
    for z in sorted(needed):
        lv = DB.Level.Create(doc, z)
        delta = z - lv.ProjectElevation
        if abs(delta) > 1e-9:
            lv.Elevation = lv.Elevation + delta
        try:
            lv.Name = "%s%.0f" % (TMP_LEVEL_PREFIX, engine.to_mm(z))
        except Exception:
            pass
        created.append(lv.Id)
    if created:
        doc.Regenerate()
    return created


def remove_temp_levels(ids):
    """Delete temporary levels nothing uses. Returns names kept."""
    kept = []
    for lid in ids:
        lv = doc.GetElement(lid)
        if lv is None:
            continue
        users = (DB.FilteredElementCollector(doc)
                 .WherePasses(DB.ElementLevelFilter(lid))
                 .WhereElementIsNotElementType().GetElementCount())
        if users == 0:
            doc.Delete(lid)
        else:
            kept.append("%s (%d element(s))" % (el_name(lv), users))
    return kept


def show_output():
    try:
        output.show()
    except Exception:
        pass


def write_log(lines):
    """Plain-text copy of the report in %TEMP%; returns its path or None."""
    import io
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "DLC_StairTransfer_log.txt")
    try:
        with io.open(path, "w", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(u"%s\n" % ln)
        return path
    except Exception:
        return None


def cleanup_new_levels(before_keys, used_keys):
    removed = []
    kept = []
    for l in DB.FilteredElementCollector(doc).OfClass(DB.Level):
        k = eid_val(l.Id)
        if k in before_keys:
            continue
        users = (DB.FilteredElementCollector(doc)
                 .WherePasses(DB.ElementLevelFilter(l.Id))
                 .WhereElementIsNotElementType().GetElementCount())
        if users == 0 and k not in used_keys:
            name = el_name(l)
            doc.Delete(l.Id)
            removed.append(name)
        else:
            kept.append(el_name(l))
    return removed, kept


# ---------------------------------------------------------------------------
# Rebuild method
# ---------------------------------------------------------------------------
def _xy(src, pt):
    q = src.xform.OfPoint(pt)
    return (q.X, q.Y)


def _curve_data(src, c):
    """("L", [p0, p1]) or ("A", [p0, p1, mid]) in host XY."""
    p0 = _xy(src, c.GetEndPoint(0))
    p1 = _xy(src, c.GetEndPoint(1))
    if isinstance(c, DB.Line):
        return ("L", [p0, p1])
    return ("A", [p0, p1, _xy(src, c.Evaluate(0.5, True))])


def read_stair_geom(job):
    """Arch stair runs/landings as plain data (host XY)."""
    src, st = job.src, job.stairs
    sdoc = src.doc
    runs = []
    for rid in st.GetStairsRuns():
        r = sdoc.GetElement(rid)
        path = list(r.GetStairsPath())
        pts = []
        if len(path) == 1 and isinstance(path[0], DB.Line):
            pts = [_xy(src, path[0].GetEndPoint(0)),
                   _xy(src, path[0].GetEndPoint(1))]
        fp = []
        for c in r.GetFootprintBoundary():
            fp.append(_xy(src, c.GetEndPoint(0)))
        runs.append(engine.RunGeom(str(r.StairsRunStyle), pts, fp,
                                   r.ActualRunWidth, r.BaseElevation,
                                   r.ActualRisersNumber))
    landings = []
    for lid in st.GetStairsLandings():
        ld = sdoc.GetElement(lid)
        landings.append(engine.LandingGeom(
            [_curve_data(src, c) for c in ld.GetFootprintBoundary()],
            ld.BaseElevation))
    base_lvl = sdoc.GetElement(p_id(st, BIP.STAIRS_BASE_LEVEL_PARAM))
    base_abs = base_lvl.ProjectElevation + p_double(st, BIP.STAIRS_BASE_OFFSET)
    return engine.StairGeom(runs, landings, st.ActualRiserHeight, base_abs)


def bring_stair_types(jobs, opts):
    """Copy each arch stair type into this model once (types copy fine even
    when the stair itself can't). Returns ({key: type id}, notes)."""
    found = {}
    notes = []
    t = DB.Transaction(doc, "DLC Stair Transfer - stair types")
    t.Start()
    try:
        for j in jobs:
            tid = j.stairs.GetTypeId()
            key = (id(j.src.doc), eid_val(tid))
            if key in found:
                continue
            ids = List[DB.ElementId]()
            ids.Add(tid)
            name = el_name(j.src.doc.GetElement(tid))
            try:
                new_ids = list(DB.ElementTransformUtils.CopyElements(
                    j.src.doc, ids, doc, DB.Transform.Identity, opts))
                pick = None
                for nid in new_ids:
                    e = doc.GetElement(nid)
                    if e is not None and el_name(e) == name:
                        pick = nid
                        break
                if pick is None and new_ids:
                    pick = new_ids[0]
                found[key] = pick
            except Exception as ex:
                found[key] = None
                notes.append("stair type '%s' could not be brought over (%s); "
                             "default type used" % (name, ex))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return found, notes


def _create_run(sid, rs, base_abs):
    def line(z):
        return DB.Line.CreateBound(DB.XYZ(rs.p0[0], rs.p0[1], z),
                                   DB.XYZ(rs.p1[0], rs.p1[1], z))
    try:   # official sample: path z = elevation above the stair base
        run = StairsRun.CreateStraightRun(doc, sid, line(rs.rel),
                                          StairsRunJustification.Center)
    except Exception as e1:
        try:  # in case this build reads it as absolute
            run = StairsRun.CreateStraightRun(doc, sid, line(base_abs + rs.rel),
                                              StairsRunJustification.Center)
        except Exception as e2:
            raise Exception("%s / %s" % (e1, e2))
    run.ActualRunWidth = rs.width
    doc.Regenerate()
    if abs(run.BaseElevation - rs.rel) > engine.mm(1.0):
        run.BaseElevation = rs.rel
        doc.Regenerate()
    return run


def _create_landing(sid, ls, base_abs):
    def loop(z):
        cl = DB.CurveLoop()
        for kind, pts in ls.curves:
            a = DB.XYZ(pts[0][0], pts[0][1], z)
            b = DB.XYZ(pts[1][0], pts[1][1], z)
            if kind == "L":
                cl.Append(DB.Line.CreateBound(a, b))
            else:
                cl.Append(DB.Arc.Create(a, b, DB.XYZ(pts[2][0], pts[2][1], z)))
        return cl
    try:   # official sample: curves at z 0, elevation passed separately
        return StairsLanding.CreateSketchedLanding(doc, sid, loop(0.0), ls.rel)
    except Exception as e1:
        try:
            return StairsLanding.CreateSketchedLanding(
                doc, sid, loop(base_abs + ls.rel), ls.rel)
        except Exception as e2:
            raise Exception("%s / %s" % (e1, e2))


def rebuild_flight(plan, spec, str_by_key, type_id, collector):
    """Build one STR stair from a BuildSpec inside a StairsEditScope."""
    base = str_by_key[plan.base_level.key]
    top = str_by_key[plan.top_level.key]
    base_abs = plan.z_bottom
    scope = DB.StairsEditScope(doc, "DLC Stair Transfer")
    try:
        sid = scope.Start(base.Id, top.Id)
    except Exception as ex:
        raise StageError("start stair edit", ex)
    t = DB.Transaction(doc, "DLC Stair Transfer - build")
    stage = "set up stair"
    n_err = len(collector.errors)
    try:
        t.Start()
        st = doc.GetElement(sid)
        if type_id is not None:
            stage = "set stair type"
            st.ChangeTypeId(type_id)
        stage = "set levels and offsets"
        set_p(st, BIP.STAIRS_BASE_OFFSET, plan.base_offset)
        set_p(st, BIP.STAIRS_TOP_OFFSET, plan.top_offset)
        rp = st.get_Parameter(BIP.STAIRS_DESIRED_NUMBER_OF_RISERS)
        if rp is not None and not rp.IsReadOnly:
            rp.Set(plan.source.risers)
        doc.Regenerate()
        for i, rs in enumerate(spec.runs):
            stage = "create run %d" % (i + 1)
            _create_run(sid, rs, base_abs)
        for i, ls in enumerate(spec.landings):
            stage = "create landing %d" % (i + 1)
            _create_landing(sid, ls, base_abs)
        stage = "finish stair"
        t.Commit()
        scope.Commit(collector)
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        if scope.IsActive:
            scope.Cancel()
        raise StageError(stage, ex)
    st = doc.GetElement(sid)
    if st is None or not st.IsValidObject:
        raise StageError("finish stair", "Revit rejected the stair: %s"
                         % ("; ".join(collector.errors[n_err:]) or "unknown"))
    return st, []


def plan_rebuilds(good):
    """Split flights into (rebuild list, copy-fallback list)."""
    rebuild, fallback = [], []
    for j, p in good:
        if SETTINGS.get("METHOD", "REBUILD") != "REBUILD":
            fallback.append((j, p, None))
            continue
        try:
            spec = engine.build_spec(read_stair_geom(j), p.riser_height)
            rebuild.append((j, p, spec))
        except engine.RebuildNotPossible as ex:
            fallback.append((j, p, "copied instead of rebuilt: %s" % ex))
        except Exception as ex:
            fallback.append((j, p, "could not read arch geometry (%s); "
                                   "copied instead" % ex))
    return rebuild, fallback


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global doc
    if revit.doc.IsFamilyDocument:
        stop("Run this in a project, not a family.")

    preselected = stairs_in_selection()
    if preselected:
        route = ROUTE_HERE     # stairs already selected: copy those
    else:
        route = forms.CommandSwitchWindow.show(
            [ROUTE_HERE, ROUTE_LINK, ROUTE_LIST],
            message="Where are the stairs you want to copy?")
    if not route:
        script.exit()

    if route == ROUTE_HERE:
        source_doc = revit.doc
        chosen = pick_here(preselected)
        if not chosen:
            script.exit()
        doc = choose_target_doc(source_doc, len(chosen))   # paste target
        xform, how = transform_for_open_doc(source_doc)
        if xform is None:
            stop("Could not line up '%s' with '%s': no link of it there and "
                 "the shared coordinates could not be verified.\n\nLink the "
                 "architecture model into the structure model (by shared "
                 "coordinates) and run again." % (source_doc.Title,
                                                  doc.Title))
        src = Source(source_doc, xform, "%s (%s)" % (source_doc.Title, how))
        picked = [(src, e, None if gp is None else xform.OfPoint(gp).Z)
                  for e, gp in chosen]
    elif route == ROUTE_LINK:
        picked = pick_from_link()
    else:
        picked = choose_from_open_doc()
    if not picked:
        script.exit()
    output.print_md("Pasting into **%s**" % doc.Title)

    jobs = collect_jobs(picked)
    if not jobs:
        stop("Nothing to copy - no usable stairs in the selection.")

    str_levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level),
                        key=lambda l: l.ProjectElevation)
    if not str_levels:
        stop("This model has no levels.")
    str_by_key = dict((eid_val(l.Id), l) for l in str_levels)
    str_recs = [engine.LevelRec(eid_val(l.Id), el_name(l), l.ProjectElevation)
                for l in str_levels]

    # group flights per source model; arch level keys are "doc:id" so two
    # source models never collide
    groups = []          # [(Source, arch_recs, [Job])]
    for j in jobs:
        for g in groups:
            if g[0].doc is j.src.doc:
                g[2].append(j)
                break
        else:
            gi = len(groups)
            recs = [engine.LevelRec("%d:%d" % (gi, eid_val(l.Id)), el_name(l),
                                    j.src.z(l.ProjectElevation))
                    for l in DB.FilteredElementCollector(j.src.doc)
                    .OfClass(DB.Level)]
            if len(set(id(x.src.doc) for x in jobs)) > 1:
                for r in recs:
                    r.name = "[%s] %s" % (j.src.doc.Title, r.name)
            groups.append((j.src, recs, [j]))

    saved_map, unticked = load_saved_choices()
    all_rows, all_flights, all_arch = [], [], []
    for src, recs, gjobs in groups:
        all_rows += engine.build_level_rows([x.flight for x in gjobs], recs,
                                            str_recs, SETTINGS, saved_map)
        all_flights += [x.flight for x in gjobs]
        all_arch += recs
    all_rows.sort(key=lambda r: -r.arch.elev)

    chosen = ask_level_map(all_rows, all_flights, all_arch, unticked)
    if not chosen:
        script.exit()
    copy_keys, level_map = chosen
    save_choices(all_rows, copy_keys, level_map)

    plans = []
    for src, recs, gjobs in groups:
        picked_flights = engine.select_flights([x.flight for x in gjobs], recs,
                                               copy_keys, SETTINGS)
        for j in gjobs:
            if j.flight in picked_flights:
                plans.append((j, engine.plan_flight(j.flight, recs, str_recs,
                                                    SETTINGS, level_map)))
    plans.sort(key=lambda jp: jp[0].flight.base_elev + jp[0].flight.dz)

    output.print_md("## Stair Transfer - preview")
    output.print_md("Source: **%s**  |  Mode: **%s**"
                    % (", ".join(sorted(set(j.src.label for j in jobs))),
                       SETTINGS["GEOMETRY_MODE"]))
    output.print_table(table_data=engine.preview_rows([p for _, p in plans]),
                       columns=engine.PREVIEW_COLUMNS)
    show_output()

    good = [(j, p) for j, p in plans if p.ok]
    bad = len(plans) - len(good)
    if not good:
        stop("No flight could be mapped to structural levels. See the table "
             "in the output window for the reason on each row.")
    if SETTINGS["DRY_RUN"]:
        forms.alert("Dry run: %d flight(s) would be created. Nothing was "
                    "changed." % len(good))
        return
    msg = "Create %d stair(s) in this model?" % len(good)
    if bad:
        msg += "\n%d flight(s) will be skipped (see output)." % bad
    if not forms.alert(msg, yes=True, no=True, title="Stair Transfer"):
        return

    target_type = find_stair_type(SETTINGS.get("TARGET_STAIR_TYPE"))
    if SETTINGS.get("TARGET_STAIR_TYPE") and target_type is None:
        output.print_md("- Stair type '%s' not found here - keeping the "
                        "copied type." % SETTINGS["TARGET_STAIR_TYPE"])

    opts = DB.CopyPasteOptions()
    opts.SetDuplicateTypeNamesHandler(UseDestinationTypes())
    before_levels = set(eid_val(l.Id) for l in
                        DB.FilteredElementCollector(doc).OfClass(DB.Level))
    collector = WarningCollector()
    results = []
    tmp_kept, removed, kept = [], [], []

    rebuild, fallback = plan_rebuilds(good)

    # --- rebuild (one undo step per flight)
    if rebuild:
        if target_type is not None:
            type_ids, type_notes = {}, []
        else:
            type_ids, type_notes = bring_stair_types(
                [j for j, _, _ in rebuild], opts)
        for j, p, spec in rebuild:
            tid = target_type.Id if target_type is not None else \
                type_ids.get((id(j.src.doc), eid_val(j.stairs.GetTypeId())))
            try:
                new_st, note = rebuild_flight(p, spec, str_by_key, tid,
                                              collector)
                results.append((p, new_st, ["rebuilt"] + type_notes + note,
                                None))
            except Exception as ex:
                results.append((p, None, [], str(ex)))

    if fallback:
        res, tmp_kept, removed, kept = run_copy_method(
            fallback, opts, str_by_key, target_type, collector,
            before_levels)
        results.extend(res)
    report(results, plans, bad, collector, tmp_kept, removed, kept)


def run_copy_method(fallback, opts, str_by_key, target_type, collector,
                    before_levels):
    """v1.1 copy path, used for flights that can't be rebuilt."""
    results = []
    t = DB.Transaction(doc, "DLC Stair Transfer - copy")
    fho = t.GetFailureHandlingOptions()
    fho.SetFailuresPreprocessor(collector)
    t.SetFailureHandlingOptions(fho)
    t.Start()
    try:
        tmp_ids = ensure_copy_levels([j for j, _, _ in fallback])
        tmp_keys = set(eid_val(i) for i in tmp_ids)
        for j, p, why in fallback:
            st_tx = DB.SubTransaction(doc)
            st_tx.Start()
            n_err = len(collector.errors)
            try:
                new_st, note = copy_flight(j, p, opts, str_by_key, target_type)
                st_tx.Commit()
                results.append((p, new_st, ([why] if why else []) + note,
                                None))
            except Exception as ex:
                st_tx.RollBack()
                msg = str(ex)
                extra = collector.errors[n_err:]
                if extra:
                    msg += " | Revit: " + "; ".join(extra)
                if why:
                    msg = "%s; then copy %s" % (why.replace(
                        "copied instead of rebuilt", "rebuild not possible"),
                        msg)
                results.append((p, None, [], msg))
        tmp_kept = remove_temp_levels(tmp_ids)
        removed, kept = [], []
        if SETTINGS["DELETE_UNUSED_COPIED_LEVELS"]:
            removed, kept = cleanup_new_levels(before_levels | tmp_keys,
                                               set(str_by_key.keys()))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return results, tmp_kept, removed, kept


def report(results, plans, bad, collector, tmp_kept, removed, kept):
    rows = []
    for p, new_st, note, err in results:
        if new_st is None:
            rows.append([p.source.label, "-", "", "FAILED: %s" % err])
            continue
        try:
            got = "%d x %.1f mm" % (new_st.ActualRisersNumber,
                                    engine.to_mm(new_st.ActualRiserHeight))
        except Exception:
            got = "?"
        status = "; ".join(p.warnings + note) or "OK"
        link = output.linkify(new_st.Id) if doc is revit.doc \
            else "#%d" % eid_val(new_st.Id)
        rows.append([p.source.label, link,
                     "%s -> %s" % (p.base_level.name, p.top_level.name)
                     + "  |  " + got, status])
    output.print_md("## Result")
    output.print_table(table_data=rows,
                       columns=["Flight", "New stair", "Levels | risers",
                                "Notes"])
    if removed:
        output.print_md("Removed %d level(s) Revit added during the copy: %s"
                        % (len(removed), ", ".join(removed)))
    if kept:
        output.print_md("**Check:** level(s) added by the copy are still in "
                        "use and were kept: %s" % ", ".join(kept))
    if tmp_kept:
        output.print_md("**Check:** temporary level(s) still in use and kept: "
                        "%s" % ", ".join(tmp_kept))
    if collector.messages:
        output.print_md("Revit warnings handled (%d):" %
                        len(collector.messages))
        for m in sorted(set(collector.messages)):
            output.print_md("- %s" % m)

    errors = []
    for p, new_st, note, err in results:
        if err and err not in errors:
            errors.append(err)
    log = ["DLC Stair Transfer v1.3.0  (method %s)" % SETTINGS.get("METHOD"),
           ""]
    log += ["PREVIEW"] + [" | ".join(r) for r in
                          engine.preview_rows([p for _, p in plans])]
    log += ["", "RESULT"] + [" | ".join(str(c) for c in r) for r in rows]
    log += ["", "ERRORS"] + errors + ["", "REVIT WARNINGS"] + \
        sorted(set(collector.messages)) + ["", "REVIT ERRORS"] + \
        collector.errors + ["", "TEMP LEVELS KEPT"] + tmp_kept
    log_path = write_log(log)
    if log_path:
        output.print_md("Log saved to `%s`" % log_path)
    show_output()

    ok = len([r for r in results if r[1] is not None])
    msg = "%d stair(s) created, %d failed, %d skipped." % (
        ok, len(results) - ok, bad)
    if errors:
        msg += "\n\nReason:\n- " + "\n- ".join(e[:300] for e in errors[:3])
        if len(errors) > 3:
            msg += "\n(+%d more)" % (len(errors) - 3)
    if log_path:
        msg += "\n\nFull report: %s" % log_path
    forms.alert(msg, title="Stair Transfer")


if __name__ == "__main__":
    main()

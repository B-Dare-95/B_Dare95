# -*- coding: utf-8 -*-

TOOL_NAME = "Family Cleaner - Project Families"
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Cleans the loadable families you pick in this project, and the families nested inside them, down to four levels. Each family is purged of unused content, its unused parameters are removed, and it is loaded back without touching the values the project already has.

After each reload the placed copies and every type's values are compared with before. If anything moved or changed, that reload is undone and the family is tried once more with its parameters left alone. MEP fittings, accessories, railing parts and profiles are skipped, because reloading them resets settings the project keeps.

Inspection Mode changes nothing: it runs with every setting on and reports what a full clean would remove.
__________________________________________________
How-to:

-> Click on the button
-> Check the families to clean in their category dropdowns, or click Pick from Model, pick placed instances of the families you want and click Finish
-> Search the list, or use All / None, to adjust the check marks
-> Set the nested levels, what to clean and the project options on the right
-> Check Inspection Mode for a report only, or leave it off to clean
-> Click Clean, save the model first if asked, and read the report
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from collections import Counter
from datetime import datetime

from pyrevit import forms, script
from System.Windows import RoutedEventHandler, Visibility
from Autodesk.Revit.DB import FilteredElementCollector, Family, FamilyInstance, TransactionGroup
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

import bd_family_cleaner as fc
import bd_family_cleaner_report as fcr
import bd_core as bd

uidoc = __revit__.ActiveUIDocument  # noqa: F821
if uidoc is None or uidoc.Document.IsFamilyDocument:
    bd.alert("Open a project first. Family Cleaner cleans the families loaded in a project.",
             TOOL_NAME,
             exit=True)
doc = uidoc.Document

memory = fc.load_memory()
remembered = memory.setdefault("families", {})

# ─────────────────────────────────────────────────────────────
#  Families
# ─────────────────────────────────────────────────────────────

placed = Counter()
for inst in FilteredElementCollector(doc).OfClass(FamilyInstance):
    try:
        placed[fc.eid_int(inst.Symbol.Family.Id)] += 1
    except Exception:
        pass

no_reload = fc.no_reload_category_ids()
families = {}
items = []
for fam in FilteredElementCollector(doc).OfClass(Family):
    try:
        if not fam.IsEditable or fam.IsInPlace:
            continue
    except Exception:
        continue
    key = fc.eid_int(fam.Id)
    name = fc.elem_name(fam)
    cat = fam.FamilyCategory
    cat_name = cat.Name if cat is not None else u"No category"
    reason = None
    if cat is not None and fc.eid_int(cat.Id) in no_reload:
        reason = u"Skipped: reloading resets settings the project keeps"
    elif remembered.get(name) == "all":
        reason = u"Kept: an earlier clean changed its placed copies"
    families[key] = (fam.Id, name)
    items.append({"key": key, "title": name, "group": cat_name,
                  "info": u"{} placed".format(placed[key]),
                  "checked": False, "enabled": reason is None, "reason": reason})
items.sort(key=lambda i: (not i["enabled"], i["title"].lower()))

if not items:
    bd.alert("This project has no editable loadable families.", TOOL_NAME, exit=True)

# ─────────────────────────────────────────────────────────────
#  Window
# ─────────────────────────────────────────────────────────────

HEADER = u"""
<TextBlock Text="Family Cleaner" Style="{StaticResource H1}" Margin="0,0,0,4"/>
<TextBlock x:Name="Subtitle" Style="{StaticResource Hint}" Margin="0,0,0,14"/>
"""

LIST_XAML = u"""
<Border Style="{StaticResource Card}" Margin="0">
    <StackPanel>
        <DockPanel Margin="0,0,0,8">
            <Button x:Name="BtnPick" DockPanel.Dock="Right" Content="Pick from Model" Style="{StaticResource Secondary}"
                    ToolTip="Pick placed instances in the model: their families become the ones to clean"/>
            <TextBlock Text="Families to clean, by category" Style="{StaticResource Label}" VerticalAlignment="Center"/>
        </DockPanel>
        <TextBlock x:Name="PickNote" Style="{StaticResource Hint}" Foreground="#F1C21B" Margin="0,0,0,8"
                   Visibility="Collapsed"/>
        <DockPanel Margin="0,0,0,8">
            <Button x:Name="BtnNone" DockPanel.Dock="Right" Content="None" Style="{StaticResource Secondary}" Margin="6,0,0,0"/>
            <Button x:Name="BtnAll" DockPanel.Dock="Right" Content="All" Style="{StaticResource Secondary}"/>
            <CheckBox x:Name="ChkInspect" DockPanel.Dock="Right" Content="Inspection Mode" Margin="10,0,10,0"
                      VerticalAlignment="Center"
                      ToolTip="Change nothing: run with every setting on and report what a full clean would remove"/>
            <Grid>
                <TextBox x:Name="SearchBox" Style="{StaticResource Input}" Height="30"/>
                <TextBlock x:Name="SearchHint" Text="Search families or categories..." Foreground="#6F6F6F" FontSize="12"
                           Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
            </Grid>
        </DockPanel>
        <ScrollViewer Height="560" VerticalScrollBarVisibility="Auto">
            <StackPanel x:Name="ListPanel"/>
        </ScrollViewer>
        <TextBlock x:Name="CountText" Style="{StaticResource Hint}" Margin="0,8,0,0"/>
    </StackPanel>
</Border>
"""

PROJECT_XAML = u"""
<Border Style="{StaticResource Card}">
    <StackPanel>
        <TextBlock Text="Project options" Style="{StaticResource Label}"/>
        <CheckBox x:Name="ChkShared" Margin="0,8,0,0"
                  Content="Also remove unused shared parameters (top-level families only)"/>
        <TextBlock Style="{StaticResource Hint}" Margin="24,2,0,0"
                   Text="Only when no schedule, view filter, project parameter or placed copy in this project uses them. Tags and other projects using the same family can't be checked."/>
        <StackPanel Orientation="Horizontal" Margin="0,10,0,0">
            <CheckBox x:Name="ChkSaveEvery" Content="Save the model every" VerticalAlignment="Center"/>
            <TextBox x:Name="TxtEvery" Text="10" Width="44" Height="26" Margin="8,0,8,0" Style="{StaticResource Input}"/>
            <TextBlock Text="families" Foreground="#F4F4F4" FontSize="12" VerticalAlignment="Center"/>
        </StackPanel>
        <TextBlock Style="{StaticResource Hint}" Margin="24,2,0,0"
                   Text="Protects a long run against a crash, but closing without saving no longer throws the run away."/>
    </StackPanel>
</Border>
"""

BODY_XAML = (HEADER + u"""
<Grid>
    <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="400"/>
    </Grid.ColumnDefinitions>
    <StackPanel Grid.Column="0" Margin="0,0,12,0">""" + LIST_XAML + u"""</StackPanel>
    <StackPanel Grid.Column="1">
        <DockPanel Margin="2,0,0,8">
            <TextBlock Text="Settings" Style="{StaticResource Label}" VerticalAlignment="Center"/>
            <TextBlock x:Name="InspectNote" Text="Inspection Mode: every setting is on" Foreground="#F1C21B"
                       FontSize="11" Margin="10,0,0,0" VerticalAlignment="Center" Visibility="Collapsed"/>
        </DockPanel>
        <StackPanel x:Name="SettingsPanel">""" + fc.OPTIONS_XAML + PROJECT_XAML + u"""</StackPanel>
    </StackPanel>
</Grid>""" + fc.BUTTONS_XAML)

# Controls kept when the window is rebuilt after Pick from Model
SETTINGS = ["Depth1", "Depth2", "Depth3", "Depth4", "ChkPurge", "ChkParams", "ScopeAll", "ScopeJunk",
            "ChkCad", "ChkShared", "ChkSaveEvery", "TxtEvery"]
KEEP = SETTINGS + ["ChkInspect", "SearchBox"]
ui_state = {"ticked": set(), "open": set(), "controls": None, "note": u"", "before_inspect": None}
choice = {"options": None}


def open_window():
    """Show the window; returns 'run', 'pick' or None (closed)."""
    window = fc.build_window(u"Family Cleaner - Project Families", 1080, BODY_XAML,
                             __revit__.MainWindowHandle)  # noqa: F821
    window.FindName("Subtitle").Text = u"{}  \u00b7  {} editable families".format(doc.Title, len(items))
    checklist = fc.GroupedCheckList(window)
    checklist.set_items(items)
    fc.wire_options(window)
    fc.restore_controls(window, ui_state["controls"])
    checklist.restore_open(ui_state["open"])
    checklist.set_checked(ui_state["ticked"])
    settings_panel = window.FindName("SettingsPanel")
    inspect_note = window.FindName("InspectNote")
    chk_inspect = window.FindName("ChkInspect")

    def show_inspection(on):
        """Grey out the settings and show them all checked; turning it off brings yours back."""
        settings_panel.IsEnabled = not on
        settings_panel.Opacity = 0.45 if on else 1.0
        inspect_note.Visibility = Visibility.Visible if on else Visibility.Collapsed

    def on_inspect(sender, args):
        if chk_inspect.IsChecked:
            ui_state["before_inspect"] = fc.save_controls(window, SETTINGS)
            fc.restore_controls(window, fc.INSPECTION_SETTINGS)
        elif ui_state["before_inspect"] is not None:
            fc.restore_controls(window, ui_state["before_inspect"])
            ui_state["before_inspect"] = None
        show_inspection(bool(chk_inspect.IsChecked))

    chk_inspect.Click += RoutedEventHandler(on_inspect)
    show_inspection(bool(chk_inspect.IsChecked))

    note = window.FindName("PickNote")
    if ui_state["note"]:
        note.Text = ui_state["note"]
        note.Visibility = Visibility.Visible

    result = {"action": None}

    def remember():
        ui_state["ticked"] = set(checklist.selected_keys())
        ui_state["open"] = checklist.open_groups()
        ui_state["controls"] = fc.save_controls(window, KEEP)

    def on_run(sender, args):
        keys = checklist.selected_keys()
        if not keys:
            bd.alert("Check at least one family, or use Pick from Model.", TOOL_NAME)
            return
        try:
            every = int(window.FindName("TxtEvery").Text)
        except Exception:
            every = 10
        remember()
        choice["options"] = fc.read_options(window)
        choice["keys"] = keys
        inspecting = bool(chk_inspect.IsChecked)
        choice["shared"] = inspecting or bool(window.FindName("ChkShared").IsChecked)
        choice["every"] = max(1, every) if (window.FindName("ChkSaveEvery").IsChecked and not inspecting) else 0
        result["action"] = "run"
        window.Close()

    def on_pick(sender, args):
        remember()
        result["action"] = "pick"
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    window.FindName("BtnRun").Click += RoutedEventHandler(on_run)
    window.FindName("BtnPick").Click += RoutedEventHandler(on_pick)
    window.FindName("BtnCancel").Click += RoutedEventHandler(on_cancel)
    fc.show_blocking(window)
    return result["action"]


def _PlacedFamilies():
    return bd.ClassFilter(FamilyInstance)


def pick_from_model():
    """Pick instances; their families replace the check marks. Esc keeps the check marks as they were."""
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, _PlacedFamilies(),
                                           "Pick instances of the families to clean, then click Finish")
    except OperationCanceledException:
        return
    picked, skipped, not_listed = {}, [], []
    enabled = dict((i["key"], i) for i in items if i["enabled"])
    listed = dict((i["key"], i) for i in items)
    for ref in refs:
        element = doc.GetElement(ref)
        try:
            fam = element.Symbol.Family
        except Exception:
            continue
        key = fc.eid_int(fam.Id)
        name = fc.elem_name(fam)
        if key in enabled:
            picked[key] = name
        elif key in listed:
            if name not in skipped:
                skipped.append(name)
        elif name not in not_listed:
            not_listed.append(name)
    if not picked and not skipped and not not_listed:
        return
    ui_state["ticked"] = set(picked)
    ui_state["open"] = set(enabled[k]["group"] for k in picked)
    controls = ui_state["controls"] or {}
    controls["SearchBox"] = u""  # show the picked families, not an old search
    ui_state["controls"] = controls
    parts = [u"Picked {} {} from the model: {}".format(
        len(picked), u"family" if len(picked) == 1 else u"families", u", ".join(sorted(picked.values())))]
    if skipped:
        parts.append(u"Skipped (reloading resets project settings, or kept after an earlier roll-back): {}".format(
            u", ".join(sorted(skipped))))
    if not_listed:
        parts.append(u"Not cleanable (in-place or not editable): {}".format(u", ".join(sorted(not_listed))))
    ui_state["note"] = u"\n".join(parts)


while True:
    action = open_window()
    if action == "pick":
        pick_from_model()
        continue
    break

options = choice["options"]
if options is None:
    script.exit()

# ─────────────────────────────────────────────────────────────
#  Checkpoint save
# ─────────────────────────────────────────────────────────────

can_save = bool(doc.PathName)
if doc.IsModified and not options.preview:
    if can_save:
        answer = bd.choose_option("This model has unsaved changes. Save it before cleaning?",
                                  TOOL_NAME,
                                  ["Save and continue", "Continue without saving", "Cancel"])
        if answer is None or answer == "Cancel":
            script.exit()
        if answer == "Save and continue":
            try:
                doc.Save()
            except Exception as ex:
                bd.alert(u"Saving failed: {}".format(ex), TOOL_NAME, exit=True)
    else:
        if not bd.confirm("This model has never been saved, so it can't be saved before or during "
                          "the clean. Continue anyway?",
                          TOOL_NAME):
            script.exit()

# ─────────────────────────────────────────────────────────────
#  Clean one family: edit, clean, reload, verify (retry without parameters)
# ─────────────────────────────────────────────────────────────

ctx = fc.ProjectContext(doc, choice["shared"])
rows = []


def clean_family(fam_id, name, cancel_check, params_allowed=True):
    """Returns 'ok', 'unchanged', 'rolled_back' or 'failed'."""
    fam = fc.find_family(doc, fam_id, name)
    if fam is None:
        node = fc.Node(name, 0, u"")
        node.status = u"Failed: the family is no longer in the project"
        rows.append(node)
        return "failed"
    fam_id = fam.Id
    skip_params = (not params_allowed) or remembered.get(name) == "params"
    before = None if options.preview else fc.snapshot(doc, fam)
    rules = fc.Rules(guard=fc.make_project_guard(ctx, fam), skip_params=skip_params)
    cleaner = fc.FamilyCleaner(options, rows, is_cancelled=cancel_check)
    try:
        fdoc = doc.EditFamily(fam)
    except Exception as ex:
        node = fc.Node(name, 0, u"")
        node.status = u"Failed to open: {}".format(ex)
        rows.append(node)
        return "failed"
    try:
        root, changed = cleaner.clean(fdoc, name, rules)
        if skip_params and not params_allowed:
            root.status += u" (retry, parameters left alone)"
        if root.status.startswith(u"Failed"):
            return "failed"
        if not changed or options.preview:
            return "unchanged" if not changed else "ok"
        tg = TransactionGroup(doc, u"Family Cleaner - {}".format(name))
        tg.Start()
        try:
            loaded = fdoc.LoadFamily(doc, fc.KeepProjectValues())
            fam_now = loaded if loaded is not None else fc.find_family(doc, fam_id, name)
            if fam_now is None:
                tg.RollBack()
                root.status = u"Rolled back: the family could not be found after the reload"
                return "failed"
            after = fc.snapshot(doc, fam_now)
            diff = fc.compare_snapshots(before, after, set(root.removed))
            if diff is None:
                tg.Assimilate()
                root.status = u"Cleaned and reloaded"
                return "ok"
            tg.RollBack()
            root.status = u"Rolled back: {}".format(diff)
            return "rolled_back"
        except Exception as ex:
            if tg.HasStarted() and not tg.HasEnded():
                tg.RollBack()
            root.status = u"Failed: reload - {}".format(ex)
            return "failed"
    finally:
        try:
            if fdoc.IsValidObject:
                fdoc.Close(False)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  Run
# ─────────────────────────────────────────────────────────────

started = datetime.now()
keys = choice["keys"]
saves = [0]
with forms.ProgressBar(title="Family Cleaner ({value} of {max_value})", cancellable=True) as pb:
    def cancelled():
        return pb.cancelled

    for n, key in enumerate(keys, 1):
        if pb.cancelled:
            break
        pb.update_progress(n, len(keys))
        fam_id, name = families[key]
        mark = len(rows)
        result = clean_family(fam_id, name, cancelled)
        if result == "rolled_back":
            for r in rows[mark + 1:]:
                r.status += u" (discarded with the reload)"
            had_params = any(r.removed for r in rows[mark:])
            if had_params and not pb.cancelled:
                retry = clean_family(fam_id, name, cancelled, params_allowed=False)
                remembered[name] = "params" if retry in ("ok", "unchanged") else "all"
            else:
                remembered[name] = "all"
        if choice["every"] and not options.preview and can_save and n % choice["every"] == 0:
            try:
                doc.Save()
                saves[0] += 1
            except Exception:
                pass

if not options.preview:
    fc.save_memory(memory)

notes = [u"Shared parameters: {}".format(
    u"{} when unused in this project".format(u"would be removed" if options.preview else u"removed")
    if choice["shared"] else u"kept")]
if saves[0]:
    notes.append(u"Saved during the run: {} times".format(saves[0]))
if not options.preview and any(r.status.startswith(u"Rolled back") for r in rows):
    notes.append(u"Families that were rolled back are remembered and handled more carefully next time "
                 u"(parameters left alone, or skipped): {}".format(fc.MEMORY_PATH))
subtitle = u"Project families  \u00b7  {} nested levels".format(options.depth)
if options.preview:
    subtitle += u"  \u00b7  Inspection Mode"
fcr.show_report(__revit__, u"Family Cleaner: {}".format(doc.Title), subtitle,  # noqa: F821
                rows, options.preview, started, notes)
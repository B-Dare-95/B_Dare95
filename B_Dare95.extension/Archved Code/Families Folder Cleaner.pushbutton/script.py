# -*- coding: utf-8 -*-

TOOL_NAME = "Family Cleaner - Library Folder"
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Cleans a whole folder of family files (.rfa) and the families nested inside them, down to four levels. Unused content is purged and unused family parameters are removed. MEP fittings and railing parts are cleaned too, because nothing is loaded into a project.

Your original files are never touched: the cleaned copies are saved into a separate output folder, keeping the subfolder structure, with the file size before and after in the report. The copies are saved in this Revit version.
__________________________________________________
How-to:

-> Click on the button
-> Browse to the library folder (tick Include subfolders if needed)
-> Check the output folder (a "_Cleaned" folder inside the library by default)
-> Tick the files to clean (search the list, or use All / None)
-> Choose how many nested levels to clean and what to clean
-> Tick Preview only for a dry run, or leave it off to clean
-> Click Clean and read the report
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

import os
from datetime import datetime

import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import FolderBrowserDialog, DialogResult

from pyrevit import forms, script
from System.Windows import RoutedEventHandler
from Autodesk.Revit.DB import SaveAsOptions

import bd_family_cleaner as fc
import bd_family_cleaner_report as fcr

app = __revit__.Application  # noqa: F821

# ─────────────────────────────────────────────────────────────
#  Window
# ─────────────────────────────────────────────────────────────

HEADER = u"""
<TextBlock Text="Family Cleaner" Style="{StaticResource H1}" Margin="0,0,0,4"/>
<TextBlock Text="Cleans a folder of .rfa files into a separate output folder. Originals are never changed."
           Style="{StaticResource Hint}" Margin="0,0,0,14"/>
"""

FOLDERS_XAML = u"""
<Border Style="{StaticResource Card}">
    <StackPanel>
        <TextBlock Text="Library folder" Style="{StaticResource Label}"/>
        <DockPanel Margin="0,8,0,0">
            <Button x:Name="BtnSource" DockPanel.Dock="Right" Content="Browse" Style="{StaticResource Secondary}" Margin="8,0,0,0"/>
            <TextBox x:Name="TxtSource" Style="{StaticResource Input}" Height="30" IsReadOnly="True"/>
        </DockPanel>
        <CheckBox x:Name="ChkSub" Content="Include subfolders" IsChecked="True" Margin="0,8,0,0"/>
        <TextBlock Text="Output folder" Style="{StaticResource Label}" Margin="0,14,0,0"/>
        <DockPanel Margin="0,8,0,0">
            <Button x:Name="BtnOutput" DockPanel.Dock="Right" Content="Browse" Style="{StaticResource Secondary}" Margin="8,0,0,0"/>
            <TextBox x:Name="TxtOutput" Style="{StaticResource Input}" Height="30" IsReadOnly="True"/>
        </DockPanel>
        <CheckBox x:Name="ChkCompact" Content="Compact the saved files (smaller, slightly slower to save)" IsChecked="True" Margin="0,8,0,0"/>
    </StackPanel>
</Border>
"""

window = fc.build_window(u"Family Cleaner - Library Folder", 640,
                         HEADER + FOLDERS_XAML + fc.LIST_XAML + fc.OPTIONS_XAML + fc.PREVIEW_XAML + fc.BUTTONS_XAML,
                         __revit__.MainWindowHandle)  # noqa: F821
window.FindName("ListTitle").Text = u"Family files"
checklist = fc.CheckList(window, noun=u"files")
fc.wire_options(window)

txt_source = window.FindName("TxtSource")
txt_output = window.FindName("TxtOutput")
chk_sub = window.FindName("ChkSub")
state = {"source": u"", "output": u"", "auto_output": True}


def pick_folder(description, start):
    dlg = FolderBrowserDialog()
    dlg.Description = description
    if start and os.path.isdir(start):
        dlg.SelectedPath = start
    if dlg.ShowDialog() == DialogResult.OK:
        return dlg.SelectedPath
    return None


def refresh_list():
    source = state["source"]
    files = fc.scan_rfa(source, bool(chk_sub.IsChecked), state["output"])
    items = []
    for path in files:
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        items.append({"key": path, "title": os.path.relpath(path, source),
                      "info": u"{:,} KB".format(int(round(size / 1024.0))), "checked": True})
    checklist.set_items(items)


def on_source(sender, args):
    folder = pick_folder("Pick the family library folder", state["source"])
    if not folder:
        return
    state["source"] = folder
    txt_source.Text = folder
    if state["auto_output"]:
        state["output"] = os.path.join(folder, u"_Cleaned")
        txt_output.Text = state["output"]
    refresh_list()


def on_output(sender, args):
    folder = pick_folder("Pick the folder for the cleaned copies", state["output"] or state["source"])
    if not folder:
        return
    state["output"] = folder
    state["auto_output"] = False
    txt_output.Text = folder
    if state["source"]:
        refresh_list()


def on_sub(sender, args):
    if state["source"]:
        refresh_list()


choice = {"options": None}


def on_run(sender, args):
    source, output = state["source"], state["output"]
    if not source:
        forms.alert("Pick the library folder first.", title=TOOL_NAME)
        return
    if not output or os.path.normcase(os.path.abspath(output)) == os.path.normcase(os.path.abspath(source)):
        forms.alert("The output folder must be different from the library folder, so the originals "
                    "are never overwritten.", title=TOOL_NAME)
        return
    keys = checklist.selected_keys()
    if not keys:
        forms.alert("Tick at least one file.", title=TOOL_NAME)
        return
    choice["options"] = fc.read_options(window)
    choice["files"] = keys
    choice["compact"] = bool(window.FindName("ChkCompact").IsChecked)
    window.Close()


def on_cancel(sender, args):
    window.Close()


window.FindName("BtnSource").Click += RoutedEventHandler(on_source)
window.FindName("BtnOutput").Click += RoutedEventHandler(on_output)
chk_sub.Click += RoutedEventHandler(on_sub)
window.FindName("BtnRun").Click += RoutedEventHandler(on_run)
window.FindName("BtnCancel").Click += RoutedEventHandler(on_cancel)
checklist.set_items([])
fc.show_blocking(window)

options = choice["options"]
if options is None:
    script.exit()

# ─────────────────────────────────────────────────────────────
#  Clean every file into the output folder
# ─────────────────────────────────────────────────────────────

source, output = state["source"], state["output"]
open_paths = set()
for d in app.Documents:
    try:
        if d.PathName:
            open_paths.add(os.path.normcase(os.path.abspath(d.PathName)))
    except Exception:
        pass

started = datetime.now()
rows = []
saved = [0]


def clean_file(path, cancel_check):
    name = os.path.splitext(os.path.basename(path))[0]
    rel = os.path.relpath(path, source)
    target = os.path.join(output, rel)
    if os.path.normcase(os.path.abspath(path)) in open_paths:
        node = fc.Node(name, 0, u"")
        node.status = u"Skipped: the file is open in Revit - close it and run again"
        rows.append(node)
        return
    try:
        fdoc = app.OpenDocumentFile(path)
    except Exception as ex:
        node = fc.Node(name, 0, u"")
        node.status = u"Failed to open: {}".format(ex)
        rows.append(node)
        return
    holder = [None]
    try:
        if not fdoc.IsFamilyDocument:
            node = fc.Node(name, 0, u"")
            node.status = u"Skipped: not a family file"
            rows.append(node)
            return
        cleaner = fc.FamilyCleaner(options, rows, is_cancelled=cancel_check)
        root, changed = cleaner.clean(fdoc, name)
        holder[0] = root
        root.size_before = os.path.getsize(path)
        if options.preview or root.status.startswith(u"Failed"):
            return
        folder = os.path.dirname(target)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        if os.path.exists(target):
            os.remove(target)  # a fresh save: no .0001 backup next to it
        save_options = SaveAsOptions()
        save_options.OverwriteExistingFile = True
        save_options.Compact = choice["compact"]
        fdoc.SaveAs(target, save_options)
        saved[0] += 1
        root.size_after = os.path.getsize(target)
        root.status = u"Cleaned and saved" if changed else u"Nothing to clean, saved a copy"
    except Exception as ex:
        node = holder[0]
        if node is None:
            node = fc.Node(name, 0, u"")
            rows.append(node)
        node.status = u"Failed: {}".format(ex)
    finally:
        try:
            if fdoc.IsValidObject:
                fdoc.Close(False)
        except Exception:
            pass


files = choice["files"]
with forms.ProgressBar(title="Family Cleaner ({value} of {max_value})", cancellable=True) as pb:
    def cancelled():
        return pb.cancelled

    for n, path in enumerate(files, 1):
        if pb.cancelled:
            break
        pb.update_progress(n, len(files))
        clean_file(path, cancelled)

notes = [u"Library: {}".format(source), u"Output: {}".format(output),
         u"Files saved: {}".format(saved[0])]
if not options.preview:
    notes.append(u"The cleaned copies are saved in this Revit version and won't open in older versions.")
fcr.show_report(__revit__, u"Family Cleaner: library",  # noqa: F821
                u"{}  \u00b7  {} nested levels".format(os.path.basename(source.rstrip(u"\\/")) or source,
                                                       options.depth),
                rows, options.preview, started, notes, mode="library", output_folder=output)